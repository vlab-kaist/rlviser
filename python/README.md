# rlviz (Python)

Replays, live streams and debug layers for the vlab-kaist rlviser fork. Usage, setup and how to
write layers: [`../docs/rlviz.md`](../docs/rlviz.md). Format: [`../docs/rlviz_format.md`](../docs/rlviz_format.md).

```sh
uv venv --python 3.12 .venv && uv pip install -p .venv -e '.[test]'
uv pip install -p .venv "RocketSim @ git+https://github.com/vlab-kaist/RocketSim@fast-step"
.venv/bin/pytest -q tests
```
