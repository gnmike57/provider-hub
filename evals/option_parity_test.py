"""Option-parity gate: the hub only ever GROWS (hundred-push W0, 2026-10-21).

Law: no operator-facing option may silently disappear. The baseline was
frozen live on 2026-10-21 from this repo's own code into
evals/parity_baseline.json (4 constellation chains, 12 hub aliases,
4 max-think names, 56 Settings env knobs, 33 routes). Every future change
must keep these sets as SUPERSETS: additions pass, removals fail this
suite. Retiring an option on purpose is a deliberate act - regenerate the
baseline, review the diff, commit it with justification:

    & <venv python> -c "import json,sys; sys.path.insert(0,'.'); \
    from dataclasses import fields; import providers, proxy_gateway; \
    d={'chains':sorted(providers.CONSTELLATION_CHAINS), \
    'hub_aliases':sorted(providers.HUB_MODEL_ALIASES), \
    'max_think':sorted(providers.MAX_THINK_NAMES), \
    'settings_fields':sorted(f.name for f in fields(proxy_gateway.Settings)), \
    'routes':sorted({getattr(r,'path','') for r in proxy_gateway.app.routes})}; \
    json.dump(d,open('evals/parity_baseline.json','w'),indent=2)"

Also pins the launcher secret law: launch_frost_hub.ps1 resolves secrets
from process/User-scope env only (Resolve-Secret preflight) and must never
again carry a literal key value - committed secrets are burned secrets.
"""

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
BASELINE = pathlib.Path(__file__).with_name("parity_baseline.json")

sys.path.insert(0, str(ROOT))


def _baseline():
    return json.loads(BASELINE.read_text(encoding="utf-8"))


def test_baseline_fixture_is_wellformed():
    data = _baseline()
    for key in ("chains", "hub_aliases", "max_think", "settings_fields", "routes"):
        assert key in data, f"baseline missing section: {key}"
        assert isinstance(data[key], list) and data[key], f"baseline section empty: {key}"


def test_constellation_chains_never_shrink():
    import providers

    missing = set(_baseline()["chains"]) - set(providers.CONSTELLATION_CHAINS)
    assert not missing, f"OPTION PARITY VIOLATION - chains removed: {sorted(missing)}"


def test_hub_model_aliases_never_shrink():
    import providers

    missing = set(_baseline()["hub_aliases"]) - set(providers.HUB_MODEL_ALIASES)
    assert not missing, f"OPTION PARITY VIOLATION - hub aliases removed: {sorted(missing)}"


def test_max_think_names_never_shrink():
    import providers

    missing = set(_baseline()["max_think"]) - set(providers.MAX_THINK_NAMES)
    assert not missing, f"OPTION PARITY VIOLATION - max-think names removed: {sorted(missing)}"


def test_settings_env_knobs_never_shrink():
    from dataclasses import fields

    import proxy_gateway

    missing = set(_baseline()["settings_fields"]) - {
        f.name for f in fields(proxy_gateway.Settings)
    }
    assert not missing, f"OPTION PARITY VIOLATION - env knobs removed: {sorted(missing)}"


def test_routes_never_shrink():
    import proxy_gateway

    missing = set(_baseline()["routes"]) - {
        getattr(r, "path", "") for r in proxy_gateway.app.routes
    }
    assert not missing, f"OPTION PARITY VIOLATION - endpoints removed: {sorted(missing)}"


def test_launcher_resolves_secrets_from_env_not_source():
    """No literal key material in launch_frost_hub.ps1: a long uninterpolated
    base64-ish right-hand side on an $env: assignment is secret-shaped
    (paths contain '$', URLs contain ':/.', so both are excluded; known model
    pins are allowlisted)."""
    safe_literals = {
        "abliterated-model-large-v2",  # PRIMARY/FALLBACK/SPECIALIST model pin
        "abliterated-model-large",     # uncensored middle pin
    }
    src = (ROOT / "launch_frost_hub.ps1").read_text(encoding="utf-8", errors="replace")
    secret_shaped = re.compile(r'\$env:[A-Za-z_]+\s*=\s*"([A-Za-z0-9+/=_-]{20,})"')
    offenders = [
        m.group(1) for m in secret_shaped.finditer(src) if m.group(1) not in safe_literals
    ]
    assert not offenders, (
        f"secret-shaped literal(s) returned to the launcher: {offenders}"
    )

