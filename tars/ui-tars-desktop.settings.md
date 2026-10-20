# UI-TARS Desktop v0.2.4 — VLM Settings (Abliteration.ai via gx10 tars-hybrid-router)

**Directive: "V2 LARGE MODEL FOR ALL"** — every TARS surface uses `abliterated-model-large-v2`
(text-only, 1M ctx, GLM-5.3). The multimodal `abliterated-model` NEVER appears in any
client-facing config; only the router (gx10, port 4001) internally uses a vision sensor to
caption screenshots into structured text for the text-only V2 large model.

## Paste-ready values

| Setting (UI label) | Value |
|---|---|
| VLM Provider | `OpenAI-compatible` (see note below) |
| VLM Base URL | `http://gx10.ayu-sidewinder.ts.net:4001/v1` |
| VLM API Key | value of Windows user env `ABLITERATION_API_KEY` |
| VLM Model Name | `abliterated-model-large-v2` |
| Use Responses API | `ON` (toggle on) |
| Language | `en` |
| Max Loop | `100` (allowed range 25–200) |
| Loop Wait Time (ms) | `1500` (allowed range 0–3000) |

Other settings left at defaults: Search Engine `google`, Operator `Local Computer Operator`,
Report Storage Base URL empty, UTIO Base URL empty.

## Where settings live (verified on this machine)

- **Settings file:** `C:\Users\lnxzf\AppData\Roaming\ui-tars-desktop\ui_tars.setting.json`
  (electron-store, `SettingStore` → `ElectronStore({ name: "ui_tars.setting" })`)
- **App install (read-only, do not touch):** `C:\Users\lnxzf\AppData\Local\UiTars\app-0.2.4\`
- **Backup of the pre-change settings file:**
  `C:\Users\lnxzf\Desktop\projects\provider-hub\tars\backups\ui_tars.setting.json.backup-20261020-175457`
- The app was NOT running while the file was edited (verified via Get-Process), so it cannot
  overwrite the new values on exit. The app is intact — nothing outside the JSON was modified.

The settings file has **already been written** with the values above. If you prefer to enter
them by hand in the app, follow the steps below.

## Step-by-step (in-app, manual path)

1. Launch **UI-TARS** (Start menu → UI-TARS).
2. Click the **Settings** (gear) icon in the left toolbar.
3. In the **VLM Settings** section:
   - **VLM Provider** (dropdown): the v0.2.4 dropdown only offers 4 preset entries
     (`Hugging Face for UI-TARS-1.0`, `Hugging Face for UI-TARS-1.5`,
     `VolcEngine Ark for Doubao-1.5-UI-TARS`, `VolcEngine Ark for Doubao-1.5-thinking-vision-pro`).
     Pick **`Hugging Face for UI-TARS-1.0`** — internally this maps to the same generic
     V1_0 prompt path that a custom `OpenAI-compatible` value uses (see note below).
   - **VLM Base URL**: paste `http://gx10.ayu-sidewinder.ts.net:4001/v1`
   - **VLM API Key**: paste the value of Windows user env `ABLITERATION_API_KEY`
   - **VLM Model Name**: paste `abliterated-model-large-v2`
   - **Use Responses API**: toggle **ON** (see fallback note below)
   - Optional: click the model **Check** button next to the fields to test connectivity.
     (`insufficient_credits` responses are expected until billing is fixed — connectivity is what matters.)
4. In **Chat Settings**:
   - **Language**: `English`
   - **Max Loop**: `100`
   - **Loop Wait Time (ms)**: `1500`
5. Close the settings panel (values auto-save).

## Note on "VLM Provider: OpenAI-compatible"

Verified against `app-0.2.4\resources\app.asar`:

- The stored `vlmProvider` value only selects the **prompt template** via `getModelVersion()`:
  `ui_tars_1_0`/`ui_tars_1_5`/`doubao_1_5`/`doubao_1_5_vl` map to specific templates and any
  other value (like our `OpenAI-compatible`) falls through to the generic **V1_0** default —
  identical to the `Hugging Face for UI-TARS-1.0` option.
- The model itself is ALWAYS called through the OpenAI SDK:
  `new OpenAI({ baseURL, apiKey, model })` → any OpenAI-compatible endpoint works, which the
  gx10 LiteLLM router (`tars-hybrid-router`) is.
- Therefore the file stores the literal value `OpenAI-compatible` (per the operator
  directive). It runs fine, but note the in-app dropdown can't display it (it shows the
  "Select VLM provider" placeholder). If you ever re-open the settings form and submit it
  manually, the dropdown validation requires one of the 4 presets — choose
  **Hugging Face for UI-TARS-1.0** (behaviorally identical, see above).

## Fallback: Use Responses API OFF

If the lead reports the router's `/v1/responses` bridge is not enabled on
`http://gx10.ayu-sidewinder.ts.net:4001/v1`, set **Use Responses API OFF** and use chat
completions instead:

1. Settings → VLM Settings → toggle **Use Responses API** OFF.
2. Or edit `C:\Users\lnxzf\AppData\Roaming\ui-tars-desktop\ui_tars.setting.json` and set
   `"useResponsesApi": false` while the app is closed.
3. Everything else stays the same — the V2 large model is served over plain
   `/v1/chat/completions` in that mode.

## Why this works with a text-only model

UI-TARS Desktop normally sends raw screenshots to a multimodal VLM. The gx10 router
(`tars-hybrid-router`, port 4001) intercepts the request, captions the screenshot with a
local vision sensor into structured text, and forwards the text to
`abliterated-model-large-v2` — so the desktop app keeps working unmodified while honoring
"V2 LARGE MODEL FOR ALL". Until Abliteration.ai billing is fixed, live runs may return
`insufficient_credits`; the configuration above is correct regardless.
