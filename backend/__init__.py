import os

# Transformers 会探测已安装的 TensorFlow/Keras。本项目只使用 PyTorch/Ollama，
# 关闭可选 TF 后端可避免全局 Keras 版本冲突阻断应用启动。
os.environ.setdefault("USE_TF", "0")

# backend package
