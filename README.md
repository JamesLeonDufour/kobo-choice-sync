<p align="center">
  <img src="docs/assets/readme-hero.svg" alt="Kobo choice sync: receive one Other value, check the CSV, and add it only if new" width="100%">
</p>

<p align="center">
  <strong>A growing choice list, one new answer at a time.</strong><br>
  KoboToolbox + GitHub Actions · Python 3.12+ · No pip dependencies
</p>

<p align="center">
  <a href="#quick-start">Quick start</a> &nbsp; · &nbsp;
  <a href="#configuration">Configuration</a> &nbsp; · &nbsp;
  <a href="#secrets">Required secrets</a> &nbsp; · &nbsp;
  <a href="#webhook">Webhook</a> &nbsp; · &nbsp;
  <a href="#troubleshooting">Troubleshooting</a>
</p>

---

When someone chooses **Other** and enters a new name, Kobo sends `person_other` to GitHub Actions. The script checks the current choices CSV, adds the value if it is new, uploads the updated file, and redeploys the form. Collectors refresh or synchronize their form to see the new option.

| 🟢 Small payload | 🔵 Duplicate matching | 🟣 Stable choices |
|---|---|---|
| Send just `person_other` for the example form. | Ignore differences in capitalization and whitespace. | Preserve existing choice IDs and keep Other at the end. |

<a id="quick-start"></a>

## 🚀 Your setup, at a glance

| Step | What to do | Where |
|---|---|---|
| **01 · Repository** | Put this project on the default branch with Actions enabled. | [GitHub setup](#repository) |
| **02 · Form** | Upload the example XLSForm and `choices.csv`, then deploy. | [Kobo form](#form) |
| **03 · Configuration** | Use the example config; set your server and field names. Keep the UID placeholder. | [Configuration](#configuration) |
| **04 · Secrets** | Add **both** `KOBO_API_TOKEN` and `KOBO_ASSET_UID`. | [Repository secrets](#secrets) |
| **05 · Webhook** | Select `person_other`, add the GitHub token header, and paste the wrapper. | [REST Service](#webhook) |
| **06 · First run** | Check the setup, submit a fictional name, and confirm it appears. | [Acceptance check](#first-run) |

> [!IMPORTANT]
> **Before your first run, add these two secrets in GitHub:**
> Open your repository → **Settings → Secrets and variables → Actions → New repository secret**.
>
> - **`KOBO_API_TOKEN`**: paste your Kobo API token.
> - **`KOBO_ASSET_UID`**: paste your Kobo project ID—the part between `/forms/` and `/summary` in your project URL.
>
> Leave `"asset_uid": "REPLACE_WITH_ASSET_UID"` unchanged in `config.json`. The workflow uses the project ID saved in GitHub, so you do not need to put it in the public file.

### What runs — and what gets downloaded

| Trigger | Choices CSV | Historical submissions |
|---|---|---|
| **Kobo webhook** | Read; update if a new value arrives | **Never downloaded** |
| **Manual run · defaults** | Read and check; dry run is on | **Never downloaded** |
| **Manual run · catch_up enabled** | Read; update if dry run is off | **Explicit full scan** |

There is no schedule. Manual runs with dry run off can also finish pending media recovery. A missed webhook must be resent or recovered with an explicit **catch_up** run; a later webhook does not recover earlier values.

```mermaid
flowchart LR
    A[Other text entered] --> B[Kobo REST Service]
    B -->|person_other| C[GitHub Actions]
    C --> D{Already in CSV?}
    D -->|Yes| E[No new row]
    D -->|No| F[Update CSV and redeploy]
    F --> G[Refresh or sync form]
    classDef source fill:#d1fae5,stroke:#059669,color:#064e3b
    classDef process fill:#e0f2fe,stroke:#0284c7,color:#0c4a6e
    classDef result fill:#ede9fe,stroke:#7c3aed,color:#4c1d95
    class A,B source
    class C,D process
    class E,F,G result
```

> [!NOTE]
> Kobo media is replaced as a complete CSV file. The script downloads that CSV to check existing choices. Blank Other text adds nothing; duplicates normally cause no upload or redeployment.

---

<a id="repository"></a>

## 🟢 01 · Create the repository

Upload this entire directory, including `.github/workflows`, to a GitHub repository with `main` as its default branch. Alternatively, from this directory:

```sh
git init -b main
git add .
git commit -m "Add Kobo choice synchronization"
git remote add origin https://github.com/OWNER/REPOSITORY.git
git push -u origin main
```

Create the empty remote repository on GitHub first. Do not commit API tokens, exports, real choice lists, or respondent data. The sample choices are fictional. Workflows use read-only repository permissions and never commit collected data.

<details>
<summary><strong>Runner usage and costs</strong></summary>

**Cost:** standard GitHub-hosted runners are free for public repositories. GitHub Free includes 2,000 runner minutes/month for private repositories, shared across the account. Both synchronization and CI consume minutes in private repositories. Each Kobo webhook or manual run starts a choice update; there are no scheduled runs. Enable an Actions budget with **Stop usage when budget limit is reached** to prevent paid overages, or use an account without a payment method. Larger runners are not used. No artifacts or caches are uploaded. Kobo's own plan limits still apply. See [GitHub billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions).

</details>

---

<a id="form"></a>

## 🔵 02 · Prepare the Kobo form

The target question must use `select_one_from_file choices.csv`. A normal embedded `select_one` list is not updated by this tool.

For a simple same-form example, create these rows in your XLSForm's `survey` worksheet:

| type | name | label | relevant | required |
|---|---|---|---|---|
| select_one_from_file choices.csv | person | Select a person | | yes |
| text | person_other | Enter the new person's name | `${person} = 'other'` | yes |

Upload [`examples/growing_choices_example.xlsx`](examples/growing_choices_example.xlsx) to Kobo to create the example project. This ready-to-upload XLSForm contains the `survey` and `settings` worksheets shown above. The choices remain in the external `choices.csv`, which must be uploaded separately as project media before deploying the form.

Upload `examples/choices.csv` to **target project → Settings → Media**, then deploy the form. Keep the filename exactly `choices.csv`. The target must be active and already deployed. The initial CSV contains `name,label` headers and an `other` choice. New choice names come from lowercase labels: `Taylor` becomes `taylor`, `Édouard` becomes `edouard`, and `John Doe` becomes `john_doe`. When names would collide, the script adds a short suffix. Existing choice names, including previously generated `auto_` names, are preserved so collected responses keep their stored values. The `other` choice is placed last whenever it exists. The original Other submission remains unchanged.

The submissions and choices CSV must belong to the same Kobo project. This version supports a select-one Other answer with a companion text field, including fields inside ordinary groups; it does not process repeat-group arrays or automatically turn every text-only registration into a choice.

<a id="configuration"></a>

## 🟣 03 · Configure the project

Start from [`config.example.json`](config.example.json). Copy it to `config.json` if you are setting up a new configuration, then edit the server and field names and commit `config.json` to the default branch. It contains configuration, never secrets. If you have already configured `config.json`, keep your settings rather than copying over them.

| File | Purpose |
|---|---|
| `config.example.json` | Reusable template matching the supplied example form |
| `config.json` | Configuration loaded by GitHub Actions; included with template defaults |
| `config.local.json` | Optional, Git-ignored local configuration; use `--config config.local.json` |

GitHub Actions loads `config.json`. The example file is your reusable starting point. Both supplied files initially contain:

```json
{
  "server": "https://eu.kobotoolbox.org",
  "asset_uid": "REPLACE_WITH_ASSET_UID",
  "csv_filename": "choices.csv",
  "select_field": "person",
  "other_value": "other",
  "text_field": "person_other"
}
```

Choose the server where your project is hosted. The example uses the EU server. Keep `person`, `person_other`, and `choices.csv` as shown when using the supplied XLSForm and CSV; change them only if your form uses different names.

To keep your project identifier out of the public repository, leave the asset UID placeholder in `config.json` and add a GitHub Actions secret named `KOBO_ASSET_UID` containing your actual project UID. The workflow passes this secret to the script, overriding the placeholder. For local use, set the same environment variable.

<details>
<summary><strong>All configuration settings and filtered choice lists</strong></summary>

| Setting | Meaning |
|---|---|
| `server` | `https://kf.kobotoolbox.org`, `https://eu.kobotoolbox.org`, or your HTTPS Kobo server origin |
| `asset_uid` | Leave `REPLACE_WITH_ASSET_UID` in the public file; `KOBO_ASSET_UID` supplies the actual project UID |
| `csv_filename` | Exact existing media filename, e.g. `choices.csv` |
| `select_field` | Submission field for the selection, e.g. `person` or `group/person` |
| `other_value` | Stored XML value of Other, usually `other`, not its displayed label |
| `text_field` | Submission field for the new option; the example form uses `person_other` |
| `extra_columns` | Mapping of additional CSV columns to submission fields; normally `{}` |
| `max_label_length` | Reject longer new labels; default 200 |
| `page_size` | Historical catch-up only: submissions per page; default 500 |
| `max_pages` | Abort before writes if pagination exceeds this limit; default 1,000 |

Find the asset UID in the project URL: `https://SERVER/#/forms/ASSET_UID/summary`. Field paths must match the JSON submissions API; groups use slashes. Do not use question labels.

The config includes only required settings. `extra_columns`, `max_label_length`, `page_size`, and `max_pages` are optional; when omitted, the script uses `{}`, `200`, `500`, and `1000` respectively. Add them only if you need to override these defaults.

For a filtered list with CSV headers `name,label,district`, configure:

```json
"extra_columns": {"district": "location/district"}
```

For filtered lists, also select each mapped filter field in the REST Service subset. New rows require that source field. Duplicate matching then uses normalized label plus the exact district value. Configure your form's `choice_filter` separately, including the desired treatment of Other. Every extra CSV column must be explicitly mapped; multilingual label columns and custom `name`/`label` column names are not supported. No existing choices are removed or renamed, even if source submissions are edited or deleted.

</details>

---

<a id="secrets"></a>

## 🟠 04 · Add both required secrets

In your GitHub repository, open **Settings → Secrets and variables → Actions**. Under **Repository secrets**, choose **New repository secret** for each entry below:

| Exact secret name | Value to paste |
|---|---|
| `KOBO_API_TOKEN` | Your Kobo API token, without a `Token ` or `Bearer ` prefix |
| `KOBO_ASSET_UID` | Your project UID, copied from between `/forms/` and `/summary` in the Kobo project URL |

For example, if the project URL is `https://eu.kobotoolbox.org/#/forms/aExampleProject123/summary`, the UID is `aExampleProject123`. This is a fictional example: use your own UID, without quotes, slashes, or the rest of the URL.

Save both entries and confirm their names appear under **Repository secrets**. Use the **Secrets** tab; the workflow reads `secrets.KOBO_ASSET_UID`, so adding it under **Variables** will not supply the value. Repository secrets are available to this workflow without selecting a GitHub environment.

The Kobo account needs permission to read project media and edit/redeploy the project. Reading submissions is needed only for optional historical catch-up.

Use Kobo **Account settings → Security** to find the token. A token inherits account access; use a dedicated account shared only into the required projects where practical. Do not paste the token into a workflow, config file, issue, or commit.

<a id="webhook"></a>

## 🟢 05 · Connect the webhook

Create a fine-grained GitHub personal access token with access to **only this repository**, and repository permission **Contents: Read and write**. Set an expiry and track its renewal. This permission is required by GitHub's repository dispatch API even though the Actions job itself only needs read access. Organization policies may require token approval.

### Create the GitHub token

In your **personal GitHub account**, open **Profile picture → Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**, or open the [token creation page](https://github.com/settings/personal-access-tokens/new) directly. Follow [GitHub's token setup instructions](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens#creating-a-fine-grained-personal-access-token).

| Token setting | Value for this repository |
|---|---|
| Token name | `Kobo webhook` |
| Expiration | Choose an expiry and set a reminder before it expires |
| Resource owner | The GitHub account or organization that owns your repository |
| Repository access | **Only select repositories** → `kobo-choice-sync` |
| Repository permissions | **Contents → Read and write** |

Click **Generate token**, copy the token, and place it in the Kobo REST Service's `Authorization` header shown below. Keep it out of `config.json` and the repository. Before expiry, create a replacement token with the same repository access and permission, update the Kobo header, verify a successful dispatch, and revoke the old token.

The two credentials have different jobs:

| Credential | Where you put it | What it allows |
|---|---|---|
| GitHub personal access token | Kobo REST Service's `Authorization: Bearer ...` header | Kobo triggers this repository's Actions workflow |
| Kobo API token | GitHub repository secret named `KOBO_API_TOKEN` | Reads and updates Kobo media and redeploys the form; reads submissions only during explicit catch-up |

The workflow's built-in GitHub credential only has read access. The personal access token is used by Kobo to call the dispatch API; the workflow does not use it to push changes to the repository.

### Register the Kobo REST Service

In the **source Kobo project → Settings → REST Services → Register a new service**:

| Field | Value |
|---|---|
| Name | GitHub choice sync |
| Endpoint URL | `https://api.github.com/repos/OWNER/REPOSITORY/dispatches` |
| Type | JSON |
| Security | No Authorization (authentication is supplied in the custom header below) |
| Enabled | Yes |
| Failure emails | Enable if desired |

Set the endpoint to `https://api.github.com/repos/OWNER/REPOSITORY/dispatches`, replacing `OWNER` and `REPOSITORY` with your GitHub account or organization and repository name.

Add custom HTTP headers:

```text
Authorization: Bearer YOUR_FINE_GRAINED_GITHUB_TOKEN
Accept: application/vnd.github+json
```

In **Select fields subset**, select only `person_other`. Under **Add Custom Wrapper**, paste exactly:

```text
{
  "event_type": "kobo_submission",
  "client_payload": {
    "other_value": %SUBMISSION%
  }
}
```

Select only `person_other`. Kobo replaces `%SUBMISSION%` with an object, for example `{"person_other":"Taylor"}`. The handler reads the text from that object and ignores missing or blank Other text. Keep `%SUBMISSION%` unquoted. The workflow rejects a missing wrapper payload instead of scanning past records. A successful dispatch returns **HTTP 204**. This confirms GitHub accepted the signal, not that synchronization finished.

You do **not** create a webhook in GitHub's Settings → Webhooks. Those send events out of GitHub. The receiving endpoint here is GitHub's authenticated repository dispatch API. Workflows must exist on the default branch.

<a id="first-run"></a>

## 🔵 06 · Check the complete flow

1. Open **Actions → Synchronize Kobo choices → Run workflow**. Leave **dry_run** checked and **catch_up** unchecked. Confirm the CSV check succeeds and no media changes.
2. Submit Other with a fictional new name in your test Kobo form.
3. Confirm the REST Service log shows HTTP 204 and an Actions run starts. Wait for its success; job startup and redeployment are asynchronous.
4. Download `choices.csv` from target Media. Confirm the new row appears and existing names are unchanged.
5. Refresh the web form or update/synchronize the form in KoboCollect. Confirm the new option can be selected. Offline or already-open forms do not update immediately.
6. Submit the same name with different capitalization or surrounding spaces. Confirm there is still only one choice for it in the same filter scope.
7. Submit two distinct new names close together. Confirm both eventually appear. If a webhook is missed, resend it from Kobo. Alternatively, explicitly enable **catch_up** on a manual run (preview with **dry_run**, then uncheck it to apply). A later webhook does not recover earlier missing values.

Before enabling this on a production form, test it on a clone. No live integration has been exercised by the included offline tests.

<details>
<summary><strong>How CSV replacement, recovery, and concurrency work</strong></summary>

- Webhook runs process only the latest submission fields carried by the event, so their workload does not grow with submission count. Manual and local runs scan submissions only with explicit **catch_up** / `--catch-up`.
- Matching ignores label case, repeated whitespace, and Unicode compatibility differences. Existing IDs and labels remain unchanged. Similar spellings are not fuzzy-matched. Extra filter values match exactly.
- The workflow serializes writers through one fixed concurrency group with `cancel-in-progress: false`. GitHub may replace an older pending run; a displaced event must be resent or recovered with explicit historical catch-up. Do not run another repository, local process, or manual media editor against the same target concurrently. There is no distributed lock across repositories.
- Kobo's files API does not update attachments in place. The script first uploads and verifies `<basename>_sync_recovery.csv`, deletes the old target, then uploads and verifies the replacement. Reserve that recovery filename for this tool.
- The target is redeployed with `PATCH deployment/` and `version_id`. Sending only `active` would not redeploy form media.
- Only after successful redeployment does the script delete the recovery file. If an upload fails, it attempts to restore the original target. If a run is interrupted or redeployment fails, the recovery file remains and the next run retries. This is recovery, not an atomic transaction: the CSV may be temporarily absent between DELETE and POST.
- The script refuses inactive projects and unpublished form edits, checks for concurrent media replacement, and passes the checked version into redeployment. Avoid editing the target during synchronization. A draft left open will block updates until you deploy or discard it.
- Logs contain counts and sanitized errors, not submitted values, API response bodies, or tokens. The selected value travels through GitHub in the dispatch event and is available in the runner event file; do not print that file or upload it as an artifact. No respondent files are committed, cached, or uploaded as artifacts. Public source code does not make your Kobo project public.

</details>

---

<a id="local-use"></a>

## 🛠️ Local use

Python 3.12 or newer; no installation or pip dependencies are needed. Put the credential in the environment using your normal secret management method, then run:

```sh
python -m kobo_sync.sync --config config.json --dry-run
python -m kobo_sync.sync --config config.json
# Optional: scan historical submissions, only when deliberately requested
python -m kobo_sync.sync --config config.json --catch-up --dry-run
python -m kobo_sync.sync --config config.json --catch-up
python -m unittest discover -s tests -v
```

Local runs are not protected by GitHub concurrency. Do not run them while the workflow is enabled or running against the same target. `config.local.json` is ignored for local configuration overrides.

GitHub repository secrets are available only in Actions. For local runs, set `KOBO_API_TOKEN` and `KOBO_ASSET_UID` in your shell environment. The script does not automatically load `.env` files or `config.local.json`; to use the latter, pass `--config config.local.json` explicitly.

<a id="troubleshooting"></a>

## 🧭 Troubleshooting

| Symptom | Check |
|---|---|
| GitHub HTTP 401/403/404 in Kobo | Repository URL, token expiry, Contents write permission, repository selection, organization approval |
| GitHub HTTP 422 | Exact JSON wrapper and event name; ensure the wrapper is enabled |
| HTTP 204 but no workflow | Workflow and config on default branch, Actions enabled, event type `kobo_submission` |
| Workflow configuration check fails | Check that `config.json` is committed |
| `Replace every configuration placeholder with a nonempty string` | Add a nonempty **repository secret** named exactly `KOBO_ASSET_UID` under Settings → Secrets and variables → Actions → Secrets. Paste only the actual project UID. Leave the public config placeholder intact, then rerun the workflow. Also check any other required config fields for placeholders. |
| Kobo HTTP 401/403/404 | Server origin, asset IDs, token validity, source and target sharing permissions |
| Draft/archival error | Deploy/discard edits or deliberately reactivate the target in Kobo |
| CSV/field error | Exact headers, unique names, group field paths, stored Other value; fix malformed historical Other submissions |
| New choice missing on device | Confirm successful redeployment, then reload/download the updated form and media |
| Recovery file remains | Read the failed Actions step, resolve the error, and rerun with dry_run unchecked |
| Unexpected submission downloads | Check that **catch_up** is unchecked; webhook runs never query submissions |

<details>
<summary><strong>Manual recovery and operational limits</strong></summary>

If automated recovery cannot proceed, disable the sync workflow, download both the target (if present) and the recovery CSV from Kobo Media, and inspect them privately. Restore the intended CSV under the original filename, redeploy, then remove the recovery file and re-enable the workflow. Do not delete the recovery file before the target is valid and deployed. This tool retains only an in-progress recovery copy, not historical backups.

Actions job startup is asynchronous. Kobo REST hooks fire for new submissions, not edits. A missed webhook is not automatically caught up by a later webhook; resend the event from Kobo or explicitly enable **catch_up** on a manual run to recover missed values. Previously added choices are never retracted. Historical deletions, spelling corrections, renaming IDs, moderation of new options, and restricted partial source access need deliberate operational handling.

</details>

## 🗂️ Files in this repository

| Path | Purpose |
|---|---|
| [`config.example.json`](config.example.json) | Template with public defaults and a UID placeholder |
| [`config.json`](config.json) | Public runtime settings loaded by Actions |
| [`examples/`](examples/) | Fictional sample choices and an uploadable XLSForm |
| [`kobo_sync/sync.py`](kobo_sync/sync.py) | Webhook processing and optional catch-up |
| [`.github/workflows/`](.github/workflows/) | Sync workflow and automated tests |
| [`.gitignore`](.gitignore) | Local configs, credentials, exports, caches, and editor files |

For private local work, use `config.local.json` and store exports in `exports/` or `private/`. These paths are ignored. The public runtime config and example template stay tracked so Actions and new installations can use them. Ignore rules do not remove files that Git already tracks.

## 📚 References

- [Original community tutorial](https://community.kobotoolbox.org/t/adding-option-to-select-one-from-a-text-box/76911/6)
- [Kobo external choices and redeployment](https://support.kobotoolbox.org/external_file.html)
- [Kobo REST services](https://support.kobotoolbox.org/rest_services.html)
- [Kobo JSON wrapper implementation](https://github.com/kobotoolbox/kpi/blob/main/kobo/apps/hook/services/service_json.py)
- [Kobo attachment API implementation](https://github.com/kobotoolbox/kpi/blob/main/kpi/serializers/v2/asset_file.py)
- [Kobo deployment serializer](https://github.com/kobotoolbox/kpi/blob/main/kpi/serializers/v2/deployment.py)
- [GitHub repository dispatch API](https://docs.github.com/en/rest/repos/repos#create-a-repository-dispatch-event)
- [GitHub concurrency](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency)

API behavior was checked against Kobo's public source and schema while building this repository. Self-hosted/older versions can differ; the live acceptance check is required.

---

<p align="center"><strong>One new value. One growing list.</strong><br><a href="LICENSE">MIT licensed</a> · Built for KoboToolbox workflows</p>
