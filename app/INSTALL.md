# Installing the AI Approve App

## One-time setup

### Step 1: Create the App from the manifest

Click this URL (replace `<base64-manifest>` with the actual encoded manifest — generate via the command below):

```bash
python -c "import base64,json; print(base64.urlsafe_b64encode(json.dumps(json.load(open('app/manifest.json'))).encode()).decode())"
```

Then visit:

```
https://github.com/settings/apps/new?manifest=<base64-manifest>
```

GitHub renders the App creation form pre-filled. Click **Create GitHub App**.

You'll land on the App's settings page. Note the **App ID** (a small integer like `1234567`).

### Step 2: Generate the private key

On the App settings page → scroll to "Private keys" → **Generate a private key**. Browser downloads `ai-approve.YYYY-MM-DD.private-key.pem`.

**Do NOT commit this file to git.** Keep it locally; you'll paste its contents into a secret in Step 4.

### Step 3: Install the App on the consumer repo

App settings → left sidebar → **Install App** → next to `AbdullahBakir97/abaya-almalakia` click **Install** → select **Only select repositories** → choose `abaya-almalakia` → **Install**.

### Step 4: Add the secrets to the consumer repo

`abaya-almalakia` → Settings → Secrets and variables → Actions → **New repository secret**:

- Name: `AI_APPROVE_APP_ID` · Value: the App ID from Step 1
- Name: `AI_APPROVE_APP_PRIVATE_KEY` · Value: the entire `.pem` file contents (include the `-----BEGIN/END-----` lines)

### Step 5: Delete the now-unused PR_REVIEW_TOKEN secret

Same Settings page → delete `PR_REVIEW_TOKEN` (no longer used after Plan 2 lands).

### Step 6: Dispatch a PR through the bot to confirm

```bash
gh workflow run ai-approve.yml -f pr=<any PR>
```

The bot should now post reviews as `ai-approve[bot]`, and APPROVE verdicts should succeed (no 422).
