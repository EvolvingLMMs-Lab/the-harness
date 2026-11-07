"""An ONNX model run by ONNX Runtime on the best device here: DirectML on Windows (any
GPU), CUDA where that build is installed, else the CPU.

    model = OnnxModel(path)                  # or OnnxModel(path, devices=["CPUExecutionProvider"])
    outputs = model.run(image)               # the inputs in the model's order, or by name
    model.provider, model.inputs             # the device it runs on, its inputs' names and shapes
"""

from pathlib import Path

PREFERRED = ("DmlExecutionProvider", "CUDAExecutionProvider", "CPUExecutionProvider")


def providers(preferred=PREFERRED) -> list[str]:
    """The preferred execution providers this ONNX Runtime has, best first."""
    import onnxruntime

    available = onnxruntime.get_available_providers()
    return [name for name in preferred if name in available]


class OnnxModel:
    def __init__(self, path, devices=None):
        import onnxruntime

        self.path = Path(path)
        options = onnxruntime.SessionOptions()
        options.graph_optimization_level = onnxruntime.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session = onnxruntime.InferenceSession(str(self.path), options, providers=devices or providers())
        self.provider = self.session.get_providers()[0]
        self.inputs = {item.name: item.shape for item in self.session.get_inputs()}

    def run(self, *arrays, **named) -> list:
        """The model's outputs for its inputs, given in its order or by name."""
        return self.session.run(None, named or dict(zip(self.inputs, arrays)))
