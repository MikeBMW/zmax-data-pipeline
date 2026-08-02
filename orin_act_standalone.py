#!/usr/bin/env python3
"""Orin ACT 独立推理 — 直接构建ACT网络+safetensors加载权重, 不依赖lerobot包"""
import json, math, os, time
from collections import deque
from collections.abc import Callable

import torch
import torch.nn.functional as F
import torchvision
from torch import Tensor, nn
from torchvision.models._utils import IntermediateLayerGetter
from torchvision.ops.misc import FrozenBatchNorm2d

ACT_DIR = os.path.expanduser("~/.zmax/act")
DEV = "cuda" if torch.cuda.is_available() else "cpu"


# ─── 从 modeling_act.py 复制的 ACT 网络核心 ───
class ACTBackbone(nn.Module):
    def __init__(self, backbone_name="resnet18", replace_final_stride_with_dilation=1, pretrained=True):
        super().__init__()
        self.backbone_name = backbone_name
        model = getattr(torchvision.models, backbone_name)(weights=None)
        num_out_channels = model.fc.in_features
        self.backbone = nn.Sequential(*list(model.children())[:-2])
        self.normalizer = nn.Identity()
        if replace_final_stride_with_dilation > 1:
            self._replace_stride_with_dilation(replace_final_stride_with_dilation)
        self.num_out_channels = num_out_channels
        self.avg_pool = nn.AdaptiveAvgPool2d(1)

    def _replace_stride_with_dilation(self, dilation):
        for i, layer in enumerate(self.backbone):
            if isinstance(layer, torchvision.models.resnet.BasicBlock):
                if i < 6:
                    layer.conv2.stride = (1, 1)
                    layer.downsample[0].stride = (1, 1) if layer.downsample else None
                    layer.conv2.dilation = (dilation, dilation)
                    layer.conv2.padding = (dilation, dilation)
                else:
                    break

    def forward(self, images):
        x = images
        for layer in self.backbone:
            x = layer(x)
        return self.avg_pool(x).flatten(1)


class TransformerLayer(nn.Module):
    def __init__(self, dim_model, n_heads, dim_feedforward, dropout=0.0, activation="relu", pre_norm=False):
        super().__init__()
        self.self_attn = nn.MultiheadAttention(dim_model, n_heads, dropout=dropout, batch_first=True)
        self.linear1 = nn.Linear(dim_model, dim_feedforward)
        self.dropout = nn.Dropout(dropout)
        self.linear2 = nn.Linear(dim_feedforward, dim_model)
        self.norm1 = nn.LayerNorm(dim_model)
        self.norm2 = nn.LayerNorm(dim_model)
        self.dropout1 = nn.Dropout(dropout)
        self.dropout2 = nn.Dropout(dropout)
        self.activation = F.relu if activation == "relu" else F.gelu
        self.pre_norm = pre_norm

    def forward(self, src, src_mask=None, src_key_padding_mask=None):
        if self.pre_norm:
            src2 = self.norm1(src)
            src2 = self._sa_block(src2, src_mask, src_key_padding_mask)
            src = src + self.dropout1(src2)
            src2 = self.norm2(src)
            src2 = self._ff_block(src2)
            src = src + self.dropout2(src2)
        else:
            src2 = self._sa_block(src, src_mask, src_key_padding_mask)
            src = src + self.dropout1(src2)
            src = self.norm1(src)
            src2 = self._ff_block(src)
            src = src + self.dropout2(src2)
            src = self.norm2(src)
        return src

    def _sa_block(self, x, attn_mask, key_padding_mask):
        x = self.self_attn(x, x, x, attn_mask=attn_mask, key_padding_mask=key_padding_mask, need_weights=False)[0]
        return self.dropout(x)

    def _ff_block(self, x):
        x = self.linear2(self.dropout(self.activation(self.linear1(x))))
        return self.dropout(x)


class TransformerEncoder(nn.Module):
    def __init__(self, encoder_layer, num_layers):
        super().__init__()
        self.layers = nn.ModuleList([encoder_layer for _ in range(num_layers)])
        self.num_layers = num_layers

    def forward(self, src, mask=None, src_key_padding_mask=None):
        output = src
        for mod in self.layers:
            output = mod(output, src_mask=mask, src_key_padding_mask=src_key_padding_mask)
        return output


class ACT(nn.Module):
    """Minimal ACT network for inference (no VAE encoder needed)."""

    def __init__(self, cfg):
        super().__init__()
        self.config = cfg
        self.input_dim = cfg["input_dim"]
        self.hidden_dim = cfg["hidden_dim"]
        self.output_dim = cfg["output_dim"]
        self.num_queries = cfg["num_queries"]
        self.dim_feedforward = cfg["dim_feedforward"]
        self.n_heads = cfg["n_heads"]
        self.num_encoder_layers = cfg["num_encoder_layers"]
        self.num_decoder_layers = cfg["num_decoder_layers"]
        self.use_vae = cfg.get("use_vae", False)
        self.latent_dim = cfg.get("latent_dim", 32)

        self.backbone = ACTBackbone(backbone_name="resnet18")
        self.encoder_img_feat_input_proj = nn.Conv2d(self.backbone.num_out_channels, self.hidden_dim, kernel_size=1)
        self.encoder_robot_state_input_proj = nn.Linear(self.input_dim, self.hidden_dim)
        self.query_pos_embed = nn.Embedding(self.num_queries, self.hidden_dim)
        self.encoder = TransformerEncoder(
            TransformerLayer(self.hidden_dim, self.n_heads, self.dim_feedforward), self.num_encoder_layers
        )
        self.decoder = TransformerEncoder(
            TransformerLayer(self.hidden_dim, self.n_heads, self.dim_feedforward), self.num_decoder_layers
        )
        self.action_head = nn.Linear(self.hidden_dim, self.output_dim)

    def forward(self, images, state):
        # 图像编码
        img_feats = self.backbone(images)  # (B, 512)
        img_emb = self.encoder_img_feat_input_proj(img_feats.unsqueeze(-1).unsqueeze(-1)).flatten(1)  # (B, hidden)
        img_emb = img_emb.unsqueeze(1)  # (B, 1, hidden)

        # state 编码
        state_emb = self.encoder_robot_state_input_proj(state).unsqueeze(1)  # (B, 1, hidden)

        # encoder
        enc_in = torch.cat([img_emb, state_emb], dim=1)
        enc_out = self.encoder(enc_in)

        # decoder queries (no VAE latent at inference)
        B = images.shape[0]
        queries = self.query_pos_embed.weight.unsqueeze(0).repeat(B, 1, 1)  # (B, num_queries, hidden)
        dec_out = self.decoder(queries)

        # action head
        actions = self.action_head(dec_out)  # (B, num_queries, output_dim)
        return actions


def build_act_from_ckpt(ckpt_path=None):
    """从 safetensors 权重推断网络结构并加载"""
    from safetensors.torch import load_file

    if ckpt_path is None:
        ckpt_path = f"{ACT_DIR}/model.safetensors"
    sd = load_file(ckpt_path)

    # 从权重推断维度
    hidden = sd["model.action_head.weight"].shape[1]
    output_dim = sd["model.action_head.weight"].shape[0]
    state_w = sd["model.encoder_robot_state_input_proj.weight"].shape[1]
    num_queries = sd["model.decoder_pos_embed.weight"].shape[0]
    # encoder/decoder 层数
    n_enc = sum(1 for k in sd if f"model.encoder.layers.{k}." in k) if any("encoder.layers.0" in k for k in sd) else 4
    # 更可靠: 数 layers 前缀
    enc_layers = set()
    for k in sd:
        if "model.encoder.layers." in k:
            enc_layers.add(int(k.split("model.encoder.layers.")[1].split(".")[0]))
    dec_layers = set()
    for k in sd:
        if "model.decoder.layers." in k:
            dec_layers.add(int(k.split("model.decoder.layers.")[1].split(".")[0]))
    n_enc = max(enc_layers) + 1 if enc_layers else 4
    n_dec = max(dec_layers) + 1 if dec_layers else 1
    dim_ff = sd["model.encoder.layers.0.linear1.weight"].shape[0]

    cfg = {
        "input_dim": state_w,
        "hidden_dim": hidden,
        "output_dim": output_dim,
        "num_queries": num_queries,
        "dim_feedforward": dim_ff,
        "n_heads": 8,
        "num_encoder_layers": n_enc,
        "num_decoder_layers": n_dec,
    }
    print(f"  结构推断: hidden={hidden}, out={output_dim}, state={state_w}, queries={num_queries}")
    print(f"  encoder={n_enc}层, decoder={n_dec}层, ff={dim_ff}")

    act = ACT(cfg)
    # 严格加载（跳过未用到的 vae 权重）
    model_keys = {k.replace("model.", "") for k in sd if k.startswith("model.") and "vae" not in k}
    missing, unexpected = act.load_state_dict(
        {k.replace("model.", ""): v for k, v in sd.items() if k.startswith("model.") and "vae" not in k},
        strict=False,
    )
    print(f"  加载: missing={len(missing)}, unexpected={len(unexpected)}")
    return act


def main():
    print("=== Orin ACT 独立推理 ===")
    print(f"torch {torch.__version__}, device: {DEV}")

    t0 = time.time()
    act = build_act_from_ckpt()
    act.to(DEV)
    act.eval()
    print(f"✅ 网络构建+权重加载: {time.time()-t0:.1f}s")

    # 推理（随机输入, 不发topic）
    batch = {
        "observation.state": torch.randn(1, 14, device=DEV),
        "observation.images.top": torch.randn(1, 3, 480, 640, device=DEV),
    }
    with torch.no_grad():
        _ = act(batch["observation.images.top"], batch["observation.state"])

    times = []
    for _ in range(5):
        t0 = time.time()
        with torch.no_grad():
            actions = act(batch["observation.images.top"], batch["observation.state"])
        times.append(time.time() - t0)

    print(f"✅ 推理成功! action shape = {tuple(actions.shape)}")
    print(f"   平均耗时: {sum(times)/len(times)*1000:.1f}ms")
    print(f"   动作样本: {[round(x,4) for x in actions[0,0,:3].tolist()]}")
    print("✅ 完成, 未发送任何topic")


if __name__ == "__main__":
    main()
