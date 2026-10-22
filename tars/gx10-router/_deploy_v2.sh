#!/usr/bin/env bash
# Roadmap 3 deploy (2026-10-22): config sanity + service restart + status.
set -uo pipefail
cd /home/nick/tars-litellm-router || exit 1
.venv/bin/python - <<'PY'
import py_compile, yaml
py_compile.compile("vision_bridge.py", doraise=True)
d = yaml.safe_load(open("litellm_config.yaml"))
names = [m["model_name"] for m in d["model_list"]]
print("vision_bridge compiles; config parses;", len(names), "model_list entries")
chains = [n for n in dict.fromkeys(names)
          if n in ("GLMMAX>DEEP>ABLITV2L", "DEEPMAX>GLM>ABLITV2L",
                   "ABLITV2L>SUB-GLM/DEEP", "GLMMAX>ABLIT-UNC>ABLITV2L",
                   "RACE:DEEPMAX/GLMMAX>ABLITV2L",
                   "GLMMAX-CONDUCTOR>DEEP+ABLITV2L",
                   "ABLITV2L-HELM>GLM-PROBE>DEEP-VERIFY")]
print("chains present:", len(chains))
assert len(chains) == 7, "expected all 7 chain ids"
PY
[ $? -eq 0 ] || { echo "CONFIG SANITY FAILED"; exit 1; }
chmod 600 router.env
export XDG_RUNTIME_DIR=/run/user/$(id -u)
systemctl --user restart litellm-router
sleep 6
systemctl --user is-active litellm-router && echo "SERVICE ACTIVE"
