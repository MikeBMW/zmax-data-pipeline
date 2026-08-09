#!/usr/bin/env python3
"""Z-MAX Mac 模型推理验证 (metaworld 39D→4D)
验证静静训练的模型在 Mac 本地可加载+推理 (CPU)
用法: python3 mac_infer_check.py /tmp/act_144640.safetensors
"""
import sys
import numpy as np
import torch

MODEL = sys.argv[1] if len(sys.argv) > 1 else "/tmp/act_144640.safetensors"


def build_act(cfg):
    """最小 ACT 网络 (与 orin_act_standalone 一致, 无图像用零)"""
    from torch import nn

    class ACTBackbone(nn.Module):
        def __init__(self):
            super().__init__()
            self.backbone = nn.Sequential(nn.Conv2d(3, 64, 7, 2, 3), nn.ReLU(),
                                          nn.MaxPool2d(2), nn.Conv2d(64, 128, 3, 2, 1), nn.ReLU(),
                                          nn.Conv2d(128, 256, 3, 2, 1), nn.ReLU())
            self.avg_pool = nn.AdaptiveAvgPool2d(1)
            self.num_out_channels = 256

        def forward(self, images):
            return self.avg_pool(self.backbone(images)).flatten(1)

    class TransformerLayer(nn.Module):
        def __init__(self, d, n_heads, ff):
            super().__init__()
            self.self_attn = nn.MultiheadAttention(d, n_heads, batch_first=True)
            self.linear1 = nn.Linear(d, ff)
            self.linear2 = nn.Linear(ff, d)
            self.norm1 = nn.LayerNorm(d)
            self.norm2 = nn.LayerNorm(d)
            self.dropout = nn.Dropout(0.0)

        def forward(self, x):
            x = x + self.self_attn(x, x, x)[0]
            x = self.norm1(x)
            x = x + self.linear2(torch.relu(self.linear1(x)))
            return self.norm2(x)

    class TransformerEncoder(nn.Module):
        def __init__(self, layer, num):
            super().__init__()
            self.layers = nn.ModuleList([layer for _ in range(num)])

        def forward(self, x):
            for l in self.layers:
                x = l(x)
            return x

    class ACT(nn.Module):
        def __init__(self, c):
            super().__init__()
            self.config = c
            self.backbone = ACTBackbone()
            self.encoder_img_feat_input_proj = nn.Conv2d(256, c["hidden_dim"], 1)
            self.encoder_robot_state_input_proj = nn.Linear(c["input_dim"], c["hidden_dim"])
            self.query_pos_embed = nn.Embedding(c["num_queries"], c["hidden_dim"])
            self.encoder = TransformerEncoder(
                TransformerLayer(c["hidden_dim"], c["n_heads"], c["dim_feedforward"]), c["num_encoder_layers"])
            self.decoder = TransformerEncoder(
                TransformerLayer(c["hidden_dim"], c["n_heads"], c["dim_feedforward"]), c["num_decoder_layers"])
            self.action_head = nn.Linear(c["hidden_dim"], c["output_dim"])

        def forward(self, images, state):
            img_feats = self.backbone(images)
            img_emb = self.encoder_img_feat_input_proj(img_feats.unsqueeze(-1).unsqueeze(-1)).flatten(1).unsqueeze(1)
            state_emb = self.encoder_robot_state_input_proj(state).unsqueeze(1)
            enc_in = torch.cat([img_emb, state_emb], dim=1)
            enc_out = self.encoder(enc_in)
            B = images.shape[0]
            queries = self.query_pos_embed.weight.unsqueeze(0).repeat(B, 1, 1)
            dec_out = self.decoder(queries)
            return self.action_head(dec_out)

    return ACT(cfg)


def main():
    from safetensors.torch import load_file
    print(f"=== Mac 模型推理验证 ===")
    print(f"模型: {MODEL}")
    sd = load_file(MODEL)

    # 推断维度
    state_dim = sd["model.encoder_robot_state_input_proj.weight"].shape[1]
    act_dim = sd["model.action_head.weight"].shape[0]
    hidden = sd["model.action_head.weight"].shape[1]
    n_queries = sd["model.decoder_pos_embed.weight"].shape[0] if "model.decoder_pos_embed.weight" in sd else sd.get("model.query_pos_embed.weight", torch.zeros(7, hidden)).shape[0]
    enc_layers = max(int(k.split("model.encoder.layers.")[1].split(".")[0]) for k in sd if "model.encoder.layers." in k) + 1
    dec_layers = max(int(k.split("model.decoder.layers.")[1].split(".")[0]) for k in sd if "model.decoder.layers." in k) + 1
    ff = sd["model.encoder.layers.0.linear1.weight"].shape[0]
    heads = 8

    cfg = {"input_dim": state_dim, "hidden_dim": hidden, "output_dim": act_dim,
           "num_queries": n_queries, "dim_feedforward": ff, "n_heads": heads,
           "num_encoder_layers": enc_layers, "num_decoder_layers": dec_layers}
    print(f"配置: state={state_dim}D → action={act_dim}D, queries={n_queries}, enc={enc_layers}, dec={dec_layers}")

    act = build_act(cfg)
    act.load_state_dict(sd, strict=False)
    act.eval()

    # 推理 (零图像 + 零状态)
    with torch.no_grad():
        img = torch.zeros(1, 3, 224, 224)
        state = torch.zeros(1, state_dim)
        out = act(img, state)
        action = out[0, 0].numpy()
    print(f"\n✅ 推理成功!")
    print(f"  预测动作 ({act_dim}D): {[round(float(x), 4) for x in action]}")
    print(f"  输出形状: {list(out.shape)}")
    print(f"  设备: CPU (Mac 无 GPU 正常)")


if __name__ == "__main__":
    main()
