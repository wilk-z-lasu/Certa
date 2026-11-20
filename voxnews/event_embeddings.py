"""Run multilingual E5 locally through ONNX Runtime."""

import os
from pathlib import Path


class E5Encoder:
    def __init__(self, directory: Path):
        self.directory = directory

    def __call__(self, articles):
        try:
            import numpy as np
            import onnxruntime as ort
            from tokenizers import Tokenizer
        except ImportError as error:
            raise ValueError("install the local embedding dependencies from requirements-events.txt") from error

        if not articles:
            return np.empty((0, 384), dtype=np.float32)
        model = self.directory / "model.onnx"
        tokenizer_file = self.directory / "tokenizer.json"
        if not model.is_file() or not tokenizer_file.is_file():
            raise ValueError(f"place the E5 model.onnx and tokenizer.json in {self.directory}")

        tokenizer = Tokenizer.from_file(str(tokenizer_file))
        tokenizer.enable_truncation(max_length=256)
        tokenizer.enable_padding(pad_id=tokenizer.token_to_id("<pad>"), pad_token="<pad>")
        options = ort.SessionOptions()
        options.intra_op_num_threads = min(8, os.cpu_count() or 1)
        session = ort.InferenceSession(str(model), sess_options=options, providers=["CPUExecutionProvider"])
        input_names = {spec.name for spec in session.get_inputs()}

        vectors = [None] * len(articles)
        by_length = sorted(range(len(articles)), key=lambda i: len(articles[i].headline) + len(articles[i].excerpt))
        for offset in range(0, len(articles), 16):
            indices = by_length[offset:offset + 16]
            encoded = tokenizer.encode_batch([f"query: {articles[i].headline}\n{articles[i].excerpt}" for i in indices])
            mask = np.asarray([row.attention_mask for row in encoded], dtype=np.int64)
            inputs = {
                "input_ids": np.asarray([row.ids for row in encoded], dtype=np.int64),
                "attention_mask": mask,
            }
            if "token_type_ids" in input_names:
                inputs["token_type_ids"] = np.asarray([row.type_ids for row in encoded], dtype=np.int64)
            hidden_states = session.run(None, inputs)[0]
            pooled = (hidden_states * mask[:, :, None]).sum(axis=1) / mask.sum(axis=1, keepdims=True)
            normalized = pooled / np.linalg.norm(pooled, axis=1, keepdims=True)
            for i, embedding in zip(indices, normalized):
                vectors[i] = embedding
        return np.asarray(vectors, dtype=np.float32)
