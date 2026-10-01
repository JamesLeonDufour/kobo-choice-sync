# 🌱 Kobo choice sync

Automatically add the text entered in a KoboToolbox **Other** field to an external choices CSV. Each webhook sends just that one field to GitHub Actions. The workflow checks the current CSV, adds the value only if it is new, updates the CSV in Kobo, and redeploys the form.

> [!TIP]
> **The webhook carries only `person_other`.** It does not send the full submission, and webhook runs do not scan past submissions.

> [!IMPORTANT]
> Kobo sends an object containing `person_other` in the repository dispatch payload. Test the REST Service in a Kobo clone before relying on it in production.

## 🚀 Setup summary

1. **Prepare the Kobo form:** use `select_one_from_file choices.csv` for the question, add the `person_other` text field for the Other answer, upload `choices.csv` as project media, and deploy the form.
2. **Configure this repository:** use `config.example.json` as the template for `config.json`, then set your Kobo server and field names; keep the asset UID placeholder. The example uses `person_other` as `text_field`.
3. **Add credentials:** save the Kobo API token as `KOBO_API_TOKEN` and the project UID as `KOBO_ASSET_UID` in GitHub Actions secrets. Create a fine-grained GitHub token with access to this repository and **Contents: Read and write**.
4. **Register the Kobo REST Service:** point it to the GitHub repository dispatch endpoint, add the GitHub token header, set the field subset to only `person_other`, and use the JSON wrapper below.
5. **Test the complete flow:** submit a test value, confirm the Actions run succeeds and the CSV updates in Kobo, then refresh or synchronize the form on a device.

> [!IMPORTANT]
> **Create both repository secrets before running the workflow:** `KOBO_API_TOKEN` and `KOBO_ASSET_UID`. Keep `"asset_uid": "REPLACE_WITH_ASSET_UID"` in the public config. The workflow supplies the real UID from the secret. Without it, the placeholder causes the run to fail.

> [!NOTE]
> Runs happen when Kobo sends a webhook or you manually start the workflow. There is no schedule. Historical submissions are read only when you explicitly enable **catch_up** on a manual run.

```mermaid
flowchart LR
    A[New Kobo submission] --> B[Kobo REST Service]
    B -->|person_other only| C[GitHub Actions]
    C -->|Read and update CSV, redeploy| D[Kobo API]
    D --> E[Refresh or synchronize form]
```

The repository is a configurable implementation, not a deployed integration. You must supply your project IDs and credentials and run the acceptance check below. Tests use simulated API responses; they do not prove compatibility with your particular Kobo deployment.

## 🔎 Exactly what gets read

| Run mode | Reads the choices CSV? | Downloads submissions? |
|---|---|---|
| Kobo webhook | Yes | **No.** Uses only the incoming `person_other` value. |
| Manual run with default settings | Yes | **No.** Checks the CSV; with dry run off, can finish pending media recovery. |
| Manual run with **catch_up** enabled | Yes | **Yes.** Explicitly scans historical submissions for missed choices. |

A webhook checks whether the incoming value already exists in the current CSV. A new value is added and the updated CSV is uploaded to Kobo, then the form is redeployed. Duplicate values normally cause no upload or redeployment. Blank Other text adds nothing. The CSV must still be downloaded and replaced as a file; this workflow does not append a row remotely in place.

## Logic at a glance

1. A collector selects **Other** and enters a new name, such as `Charlie`.
2. Kobo REST Services sends only the configured Other text field for that submission to GitHub's `repository_dispatch` endpoint.
3. GitHub Actions runs the Python script, which reads the current choices CSV and checks only that value. It does not fetch or scan source submissions during webhook runs.
4. The script adds missing Other names to the CSV, ignoring differences in capitalization and whitespace. Existing choices and their IDs are preserved; repeating `Charlie` does not add another row. If the CSV contains an `other` choice, it stays at the end of the list.
5. If an update is needed, the script creates a recovery copy, replaces `choices.csv` in **Kobo project Media**, and redeploys the target form. Collectors refresh the web form or synchronize KoboCollect to see the new choice.

The repository's `examples/choices.csv` is just the initial sample. GitHub Actions updates the CSV hosted in Kobo, without committing respondent data to GitHub. Runs start from a Kobo webhook or the manual **Run workflow** button; there is no timer.

## 1. Create the GitHub repository

Upload this entire directory, including `.github/workflows`, to a GitHub repository with `main` as its default branch. Alternatively, from this directory:

```sh
git init -b main
git add .
git commit -m "Add Kobo choice synchronization"
git remote add origin https://github.com/OWNER/REPOSITORY.git
git push -u origin main
```

Create the empty remote repository on GitHub first. Do not commit API tokens, exports, real choice lists, or respondent data. The sample choices are fictional. Workflows use read-only repository permissions and never commit collected data.

**Cost:** standard GitHub-hosted runners are free for public repositories. GitHub Free includes 2,000 runner minutes/month for private repositories, shared across the account. Both synchronization and CI consume minutes in private repositories. Each Kobo webhook or manual run starts a choice update; there are no scheduled runs. Enable an Actions budget with **Stop usage when budget limit is reached** to prevent paid overages, or use an account without a payment method. Larger runners are not used. No artifacts or caches are uploaded. Kobo's own plan limits still apply. See [GitHub billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions).

## 2. Prepare the form and initial CSV

The target question must use `select_one_from_file choices.csv`. A normal embedded `select_one` list is not updated by this tool.

For a simple same-form example, create these rows in your XLSForm's `survey` worksheet:

| type | name | label | relevant | required |
|---|---|---|---|---|
| select_one_from_file choices.csv | person | Select a person | | yes |
| text | person_other | Enter the new person's name | `${person} = 'other'` | yes |

Upload [`examples/growing_choices_example.xlsx`](examples/growing_choices_example.xlsx) to Kobo to create the example project. This ready-to-upload XLSForm contains the `survey` and `settings` worksheets shown above. The choices remain in the external `choices.csv`, which must be uploaded separately as project media before deploying the form.

Upload `examples/choices.csv` to **target project → Settings → Media**, then deploy the form. Keep the filename exactly `choices.csv`. The target must be active and already deployed. The initial CSV contains `name,label` headers and an `other` choice. New choice names come from lowercase labels: `Taylor` becomes `taylor`, `Édouard` becomes `edouard`, and `John Doe` becomes `john_doe`. When names would collide, the script adds a short suffix. Existing choice names, including previously generated `auto_` names, are preserved so collected responses keep their stored values. The `other` choice is placed last whenever it exists. The original Other submission remains unchanged.

The submissions and choices CSV must belong to the same Kobo project. This version supports a select-one Other answer with a companion text field, including fields inside ordinary groups; it does not process repeat-group arrays or automatically turn every text-only registration into a choice.

## 3. Configure the synchronization

Start from [`config.example.json`](config.example.json). Copy it to `config.json` if you are setting up a new configuration, then edit the server and field names and commit `config.json` to the default branch. It contains configuration, never secrets. If you have already configured `config.json`, keep your settings rather than copying over them.

| File | Purpose |
|---|---|
| `config.example.json` | Reusable template matching the supplied example form |
| `config.json` | Configuration loaded by GitHub Actions; included with template defaults |
| `config.local.json` | Optional, Git-ignored local configuration; use `--config config.local.json` |

The workflow reads `config.json`, not `config.example.json`. Both supplied files initially contain:

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

## 4. Add both required repository secrets

In your GitHub repository, open **Settings → Secrets and variables → Actions**. Under **Repository secrets**, choose **New repository secret** for each entry below:

| Exact secret name | Value to paste |
|---|---|
| `KOBO_API_TOKEN` | Your Kobo API token, without a `Token ` or `Bearer ` prefix |
| `KOBO_ASSET_UID` | Your project UID, copied from between `/forms/` and `/summary` in the Kobo project URL |

For example, if the project URL is `https://eu.kobotoolbox.org/#/forms/aExampleProject123/summary`, the UID is `aExampleProject123`. This is a fictional example: use your own UID, without quotes, slashes, or the rest of the URL.

Save both entries and confirm their names appear under **Repository secrets**. Use the **Secrets** tab; the workflow reads `secrets.KOBO_ASSET_UID`, so adding it under **Variables** will not supply the value. Repository secrets are available to this workflow without selecting a GitHub environment.

The Kobo account needs permission to read project media and edit/redeploy the project. Reading submissions is needed only for optional historical catch-up.

Use Kobo **Account settings → Security** to find the token. A token inherits account access; use a dedicated account shared only into the required projects where practical. Do not paste the token into a workflow, config file, issue, or commit.

## 5. Configure the direct webhook

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

```json
{
  "event_type": "kobo_submission",
  "client_payload": {"other_value": %SUBMISSION%}
}
```

Select only `person_other`. Kobo replaces `%SUBMISSION%` with an object, for example `{"person_other":"Taylor"}`. The handler reads the text from that object and ignores missing or blank Other text. Keep `%SUBMISSION%` unquoted. The workflow rejects a missing wrapper payload instead of scanning past records. A successful dispatch returns **HTTP 204**. This confirms GitHub accepted the signal, not that synchronization finished.

You do **not** create a webhook in GitHub's Settings → Webhooks. Those send events out of GitHub. The receiving endpoint here is GitHub's authenticated repository dispatch API. Workflows must exist on the default branch.

## 6. Run the acceptance check

1. Open **Actions → Synchronize Kobo choices → Run workflow**. Leave **dry_run** checked and **catch_up** unchecked. Confirm the CSV check succeeds and no media changes.
2. Submit Other with a fictional new name in your test Kobo form.
3. Confirm the REST Service log shows HTTP 204 and an Actions run starts. Wait for its success; job startup and redeployment are asynchronous.
4. Download `choices.csv` from target Media. Confirm the new row appears and existing names are unchanged.
5. Refresh the web form or update/synchronize the form in KoboCollect. Confirm the new option can be selected. Offline or already-open forms do not update immediately.
6. Submit the same name with different capitalization or surrounding spaces. Confirm there is still only one choice for it in the same filter scope.
7. Submit two distinct new names close together. Confirm both eventually appear. If a webhook is missed, resend it from Kobo. Alternatively, explicitly enable **catch_up** on a manual run (preview with **dry_run**, then uncheck it to apply). A later webhook does not recover earlier missing values.

Before enabling this on a production form, test it on a clone. No live integration has been exercised by the included offline tests.

## How it stays consistent

- Webhook runs process only the latest submission fields carried by the event, so their workload does not grow with submission count. Manual and local runs scan submissions only with explicit **catch_up** / `--catch-up`.
- Matching ignores label case, repeated whitespace, and Unicode compatibility differences. Existing IDs and labels remain unchanged. Similar spellings are not fuzzy-matched. Extra filter values match exactly.
- The workflow serializes writers through one fixed concurrency group with `cancel-in-progress: false`. GitHub may replace an older pending run; a displaced event must be resent or recovered with explicit historical catch-up. Do not run another repository, local process, or manual media editor against the same target concurrently. There is no distributed lock across repositories.
- Kobo's files API does not update attachments in place. The script first uploads and verifies `<basename>_sync_recovery.csv`, deletes the old target, then uploads and verifies the replacement. Reserve that recovery filename for this tool.
- The target is redeployed with `PATCH deployment/` and `version_id`. Sending only `active` would not redeploy form media.
- Only after successful redeployment does the script delete the recovery file. If an upload fails, it attempts to restore the original target. If a run is interrupted or redeployment fails, the recovery file remains and the next run retries. This is recovery, not an atomic transaction: the CSV may be temporarily absent between DELETE and POST.
- The script refuses inactive projects and unpublished form edits, checks for concurrent media replacement, and passes the checked version into redeployment. Avoid editing the target during synchronization. A draft left open will block updates until you deploy or discard it.
- Logs contain counts and sanitized errors, not submitted values, API response bodies, or tokens. The selected value travels through GitHub in the dispatch event and is available in the runner event file; do not print that file or upload it as an artifact. No respondent files are committed, cached, or uploaded as artifacts. Public source code does not make your Kobo project public.

## Local use and tests

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

## Troubleshooting and recovery

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

If automated recovery cannot proceed, disable the sync workflow, download both the target (if present) and the recovery CSV from Kobo Media, and inspect them privately. Restore the intended CSV under the original filename, redeploy, then remove the recovery file and re-enable the workflow. Do not delete the recovery file before the target is valid and deployed. This tool retains only an in-progress recovery copy, not historical backups.

Actions job startup is asynchronous. Kobo REST hooks fire for new submissions, not edits. A missed webhook is not automatically caught up by a later webhook; resend the event from Kobo or explicitly enable **catch_up** on a manual run to recover missed values. Previously added choices are never retracted. Historical deletions, spelling corrections, renaming IDs, moderation of new options, and restricted partial source access need deliberate operational handling.

## References

- [Original community tutorial](https://community.kobotoolbox.org/t/adding-option-to-select-one-from-a-text-box/76911/6)
- [Kobo external choices and redeployment](https://support.kobotoolbox.org/external_file.html)
- [Kobo REST services](https://support.kobotoolbox.org/rest_services.html)
- [Kobo JSON wrapper implementation](https://github.com/kobotoolbox/kpi/blob/main/kobo/apps/hook/services/service_json.py)
- [Kobo attachment API implementation](https://github.com/kobotoolbox/kpi/blob/main/kpi/serializers/v2/asset_file.py)
- [Kobo deployment serializer](https://github.com/kobotoolbox/kpi/blob/main/kpi/serializers/v2/deployment.py)
- [GitHub repository dispatch API](https://docs.github.com/en/rest/repos/repos#create-a-repository-dispatch-event)
- [GitHub concurrency](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency)

API behavior was checked against Kobo's public source and schema while building this repository. Self-hosted/older versions can differ; the live acceptance check is required.
