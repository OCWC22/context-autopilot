"""Context Autopilot.

Pipeline: export traces -> build memory + SFT + RL/eval tasks -> train
(SFT warm-up then verifiable-reward GRPO) -> serve on Modal/vLLM -> route.

The `autopilot.export`, `autopilot.dataset`, `autopilot.rewards.reward_funcs`,
`autopilot.rewards.sandbox`, and `autopilot.serve.router` modules are
standard-library only and run without a GPU. Training and serving modules pull
heavy optional deps (torch/trl/verifiers/vllm/modal) and are imported lazily.
"""

__version__ = "0.1.0"
