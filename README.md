# Kobo choice sync

Automatically add text entered under **Other** to a KoboToolbox external choices CSV. Kobo sends a webhook directly to GitHub; GitHub Actions reconciles the submissions, replaces the CSV in Kobo, and redeploys the target form. No Power Automate, webhook server, database, third-party Python package, or paid relay is required.

Choice updates run only when Kobo sends a webhook or you start the workflow manually. There is no scheduled synchronization.

```mermaid
flowchart LR
    A[New Kobo submission] --> B[Kobo REST Service]
    B -->|Empty dispatch payload| C[GitHub Actions]
    C -->|Read submissions and current CSV| D[Kobo API]
    C -->|Merge, replace CSV, redeploy| D
    D --> E[Collectors refresh or synchronize form]
```

The repository is a configurable implementation, not a deployed integration. You must supply your project IDs and credentials and run the acceptance check below. Tests use simulated API responses; they do not prove compatibility with your particular Kobo deployment.

## Logic at a glance

1. A collector selects **Other** and enters a new name, such as `Charlie`.
2. Kobo REST Services sends an authenticated request to GitHub's `repository_dispatch` endpoint. The request is a signal; it contains no submission data.
3. GitHub Actions runs the Python script, which reads the current choices CSV and all source submissions directly from Kobo. Reading all submissions lets the next successful run catch up missed webhooks.
4. The script adds missing Other names to the CSV, ignoring differences in capitalization and whitespace. Existing choices and their IDs are preserved; repeating `Charlie` does not add another row.
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

The `examples/survey.csv` and `examples/settings.csv` files contain the same worksheet rows for reference; they are **not directly uploadable XLSForms**.

Upload `examples/choices.csv` to **target project → Settings → Media**, then deploy the form. Keep the filename exactly `choices.csv`. The target must be active and already deployed. The initial CSV contains `name,label` headers and an `other` choice. New choice names come from lowercase labels: `Taylor` becomes `james`, `Édouard` becomes `edouard`, and `John Doe` becomes `john_doe`. When names would collide, the script adds a short suffix. Existing choice names, including previously generated `auto_` names, are preserved so collected responses keep their stored values. The original Other submission remains unchanged.

For another target project, use its asset UID in the next step and attach the CSV to that project. Both projects must be on the configured server and accessible using the same Kobo account/token. This version supports a select-one Other answer with a companion text field, including fields inside ordinary groups; it does not process repeat-group arrays or automatically turn every text-only registration into a choice.

## 3. Configure the synchronization

Copy `config.example.json` to `config.json` and edit it. Commit `config.json` to the default branch. It contains configuration, never secrets.

| Setting | Meaning |
|---|---|
| `server` | `https://kf.kobotoolbox.org`, `https://eu.kobotoolbox.org`, or your HTTPS Kobo server origin |
| `source_asset_uid` | Project receiving the submissions |
| `target_asset_uid` | Project containing the choices CSV; use the source UID for the same form |
| `csv_filename` | Exact existing media filename, e.g. `choices.csv` |
| `select_field` | Submission field for the selection, e.g. `person` or `group/person` |
| `other_value` | Stored XML value of Other, usually `other`, not its displayed label |
| `text_field` | Submission field for the new option, e.g. `person_other` |
| `extra_columns` | Mapping of additional CSV columns to submission fields; normally `{}` |
| `max_label_length` | Reject longer new labels; default 200 |
| `page_size` | Submissions requested per page; default 500 |
| `max_pages` | Abort before writes if pagination exceeds this limit; default 1,000 |

Find each asset UID in its project URL: `https://SERVER/#/forms/ASSET_UID/summary`. Field paths must match the JSON submissions API; groups use slashes. Do not use question labels.

The example config includes only required settings. `extra_columns`, `max_label_length`, `page_size`, and `max_pages` are optional; when omitted, the script uses `{}`, `200`, `500`, and `1000` respectively. Add them only if you need to override these defaults.

For a filtered list with CSV headers `name,label,district`, configure:

```json
"extra_columns": {"district": "location/district"}
```

New rows require that source field. Duplicate matching then uses normalized label plus the exact district value. Configure your form's `choice_filter` separately, including the desired treatment of Other. Every extra CSV column must be explicitly mapped; multilingual label columns and custom `name`/`label` column names are not supported. No existing choices are removed or renamed, even if source submissions are edited or deleted.

## 4. Add the Kobo credential

In GitHub, open **Settings → Secrets and variables → Actions → New repository secret**:

- Name: `KOBO_API_TOKEN`
- Value: the API token from the Kobo account with permission to read all relevant source submissions and edit/redeploy the target project.

Use Kobo **Account settings → Security** to find the token. A token inherits account access; use a dedicated account shared only into the required projects where practical. Do not paste the token into a workflow, config file, issue, or commit.

## 5. Configure the direct webhook

Create a fine-grained GitHub personal access token with access to **only this repository**, and repository permission **Contents: Read and write**. Set an expiry and track its renewal. This permission is required by GitHub's repository dispatch API even though the Actions job itself only needs read access. Organization policies may require token approval.

### Create the GitHub token

In your **personal GitHub account**, open **Profile picture → Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**, or open the [token creation page](https://github.com/settings/personal-access-tokens/new) directly. Follow [GitHub's token setup instructions](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens#creating-a-fine-grained-personal-access-token).

| Token setting | Value for this repository |
|---|---|
| Token name | `Kobo webhook` |
| Expiration | Choose an expiry and set a reminder before it expires |
| Resource owner | `OWNER` |
| Repository access | **Only select repositories** → `kobo-choice-sync` |
| Repository permissions | **Contents → Read and write** |

Click **Generate token**, copy the token, and place it in the Kobo REST Service's `Authorization` header shown below. Keep it out of `config.json` and the repository. Before expiry, create a replacement token with the same repository access and permission, update the Kobo header, verify a successful dispatch, and revoke the old token.

The two credentials have different jobs:

| Credential | Where you put it | What it allows |
|---|---|---|
| GitHub personal access token | Kobo REST Service's `Authorization: Bearer ...` header | Kobo triggers this repository's Actions workflow |
| Kobo API token | GitHub repository secret named `KOBO_API_TOKEN` | The workflow reads submissions, updates Kobo media, and redeploys the form |

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

For this repository, the endpoint is `https://api.github.com/repos/OWNER/kobo-choice-sync/dispatches`. Replace the owner and repository if you use a fork.

Add custom HTTP headers:

```text
Authorization: Bearer YOUR_FINE_GRAINED_GITHUB_TOKEN
Accept: application/vnd.github+json
```

Choose **Add Custom Wrapper** and paste `examples/webhook-wrapper.json`:

```json
{
  "event_type": "kobo_submission",
  "client_payload": {}
}
```

The empty payload is intentional. The script reads the authoritative data from Kobo; it does not need `%SUBMISSION%`, names, IDs, or any respondent data in GitHub's dispatch event. Kobo's JSON wrapper supports constant JSON. You may select `_id` as the field subset to minimize internal processing; the constant wrapper discards it regardless. A successful dispatch returns **HTTP 204**. This confirms GitHub accepted the signal, not that synchronization finished.

You do **not** create a webhook in GitHub's Settings → Webhooks. Those send events out of GitHub. The receiving endpoint here is GitHub's authenticated repository dispatch API. Workflows must exist on the default branch.

## 6. Run the acceptance check

1. Open **Actions → Synchronize Kobo choices → Run workflow**. Leave **dry_run** checked. Confirm a successful read and that no media changed.
2. Submit Other with a fictional new name in your test Kobo form.
3. Confirm the REST Service log shows HTTP 204 and an Actions run starts. Wait for its success; job startup and redeployment are asynchronous.
4. Download `choices.csv` from target Media. Confirm the new row appears and existing names are unchanged.
5. Refresh the web form or update/synchronize the form in KoboCollect. Confirm the new option can be selected. Offline or already-open forms do not update immediately.
6. Submit the same name with different capitalization or surrounding spaces. Confirm there is still only one choice for it in the same filter scope.
7. Submit two distinct new names close together. Confirm both eventually appear. If a webhook is missed, run the workflow manually with **dry_run** unchecked to catch up, or wait for the next successful webhook.

Before enabling this on a production form, test it on a clone. No live integration has been exercised by the included offline tests.

## How it stays consistent

- Every run scans all source submissions using paginated, field-limited requests. It merges Other entries into the current CSV. This catches up missed/coalesced webhook runs without requiring a database or cursor. Cost and runtime grow with submission count.
- Matching ignores label case, repeated whitespace, and Unicode compatibility differences. Existing IDs and labels remain unchanged. Similar spellings are not fuzzy-matched. Extra filter values match exactly.
- The workflow serializes writers through one fixed concurrency group with `cancel-in-progress: false`. GitHub may replace an older pending run; reconciliation makes individual signal loss recoverable. Do not run another repository, local process, or manual media editor against the same target concurrently. There is no distributed lock across repositories.
- Kobo's files API does not update attachments in place. The script first uploads and verifies `<basename>_sync_recovery.csv`, deletes the old target, then uploads and verifies the replacement. Reserve that recovery filename for this tool.
- The target is redeployed with `PATCH deployment/` and `version_id`. Sending only `active` would not redeploy form media.
- Only after successful redeployment does the script delete the recovery file. If an upload fails, it attempts to restore the original target. If a run is interrupted or redeployment fails, the recovery file remains and the next run retries. This is recovery, not an atomic transaction: the CSV may be temporarily absent between DELETE and POST.
- The script refuses inactive projects and unpublished form edits, checks for concurrent media replacement, and passes the checked version into redeployment. Avoid editing the target during synchronization. A draft left open will block updates until you deploy or discard it.
- Logs contain counts and sanitized errors, not submitted values, API response bodies, or tokens. Collected values exist transiently in runner memory. No respondent files are committed, cached, or uploaded as artifacts. Public source code does not make your Kobo project public.

## Local use and tests

Python 3.12 or newer; no installation or pip dependencies are needed. Put the credential in the environment using your normal secret management method, then run:

```sh
python -m kobo_sync.sync --config config.json --dry-run
python -m kobo_sync.sync --config config.json
python -m unittest discover -s tests -v
```

Local runs are not protected by GitHub concurrency. Do not run them while the workflow is enabled or running against the same target. `config.local.json` is ignored for local configuration overrides.

## Troubleshooting and recovery

| Symptom | Check |
|---|---|
| GitHub HTTP 401/403/404 in Kobo | Repository URL, token expiry, Contents write permission, repository selection, organization approval |
| GitHub HTTP 422 | Exact JSON wrapper and event name; ensure the wrapper is enabled |
| HTTP 204 but no workflow | Workflow and config on default branch, Actions enabled, event type `kobo_submission` |
| Workflow configuration check fails | Create and commit `config.json` |
| Kobo HTTP 401/403/404 | Server origin, asset IDs, token validity, source and target sharing permissions |
| Draft/archival error | Deploy/discard edits or deliberately reactivate the target in Kobo |
| CSV/field error | Exact headers, unique names, group field paths, stored Other value; fix malformed historical Other submissions |
| New choice missing on device | Confirm successful redeployment, then reload/download the updated form and media |
| Recovery file remains | Read the failed Actions step, resolve the error, and rerun with dry_run unchecked |
| Too slow for large forms | Reduce frequency or adapt to durable incremental state; do not truncate pagination |

If automated recovery cannot proceed, disable the sync workflow, download both the target (if present) and the recovery CSV from Kobo Media, and inspect them privately. Restore the intended CSV under the original filename, redeploy, then remove the recovery file and re-enable the workflow. Do not delete the recovery file before the target is valid and deployed. This tool retains only an in-progress recovery copy, not historical backups.

Actions job startup is asynchronous. Kobo REST hooks fire for new submissions, not edits; values found in edited submissions are picked up on the next successful webhook or manual run. Without a schedule, missed webhooks and interrupted runs wait for another webhook or a manual run. Previously added choices are never retracted. Historical deletions, spelling corrections, renaming IDs, moderation of new options, and restricted partial source access need deliberate operational handling.

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
