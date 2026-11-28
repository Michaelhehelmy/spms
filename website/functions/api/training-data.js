/**
 * Cloudflare Pages Function: receive opt-in sanitized SPMS training data and
 * store it in GitHub (Option A: commit JSON to inbox path, create notification issue).
 *
 * Secrets / env vars:
 *   TRAINING_GITHUB_TOKEN or REPORT_GITHUB_TOKEN (required) - token with contents:write + issues:write
 *   TRAINING_GITHUB_REPO or REPORT_GITHUB_REPO (optional) - default "Michaelhehelmy/spms"
 *   TRAINING_INBOX_PATH (optional) - default "data/training-inbox"
 *   TRAINING_MAX_BYTES (optional) - default 5242880 (5 MB)
 */

function jsonResponse(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { 'Content-Type': 'application/json; charset=utf-8' },
  });
}

function safeName(s) {
  return String(s || '').replace(/[^a-zA-Z0-9._-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 80) || 'upload';
}

function base64Utf8(str) {
  // btoa expects latin1; encode UTF-8 bytes manually
  const bytes = new TextEncoder().encode(str);
  let bin = '';
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
  return btoa(bin);
}

export async function onRequestPost(context) {
  const { request, env } = context;
  const maxBytes = parseInt(env.TRAINING_MAX_BYTES || '5242880', 10);
  try {
    const contentType = (request.headers.get('content-type') || '').toLowerCase();
    if (!contentType.includes('application/json')) {
      return jsonResponse({ ok: false, error: 'Content-Type must be application/json.' }, 415);
    }
    const raw = await request.text();
    if (!raw || raw.length > maxBytes) {
      return jsonResponse({ ok: false, error: `Payload too large or empty (max ${maxBytes} bytes).` }, 413);
    }

    let data;
    try { data = JSON.parse(raw); } catch { return jsonResponse({ ok: false, error: 'Invalid JSON.' }, 400); }
    if (typeof data !== 'object' || data === null) return jsonResponse({ ok: false, error: 'Invalid payload.' }, 400);
    if (data.package_type !== 'spms_training_data_share') {
      return jsonResponse({ ok: false, error: 'Invalid package_type.' }, 400);
    }
    if (!data.consent || !data.consent.opt_in) {
      return jsonResponse({ ok: false, error: 'Missing opt-in consent.' }, 400);
    }

    const token = env.TRAINING_GITHUB_TOKEN || env.REPORT_GITHUB_TOKEN || env.GITHUB_TOKEN;
    if (!token) {
      return jsonResponse({ ok: false, error: 'Training upload not configured on server (missing token).' }, 503);
    }
    const repo = (env.TRAINING_GITHUB_REPO || 'Michaelhehelmy/spms-training-inbox').trim();
    const inbox = (env.TRAINING_INBOX_PATH || 'data/training-inbox').replace(/^\/+|\/+$/g, '');
    const now = new Date();
    const ym = `${now.getUTCFullYear()}-${String(now.getUTCMonth() + 1).padStart(2, '0')}`;
    const ts = now.toISOString().replace(/[:.]/g, '-');
    const sha = (data.sha256 || '').slice(0, 16) || 'nosha';
    const path = `${inbox}/${ym}/${ts}-${safeName(sha)}.json`;

    // Commit file via Contents API
    const contentB64 = base64Utf8(raw);
    const putRes = await fetch(`https://api.github.com/repos/${repo}/contents/${encodeURIComponent(path).replace(/%2F/g, '/')}`, {
      method: 'PUT',
      headers: {
        'Authorization': `Bearer ${token}`,
        'Accept': 'application/vnd.github+json',
        'User-Agent': 'spms-training-share',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        message: `training-data: inbox upload ${ym} ${sha}`,
        content: contentB64,
        branch: env.TRAINING_GITHUB_BRANCH || undefined,
      }),
    });
    const putText = await putRes.text().catch(() => '');
    let putJson = {};
    try { putJson = JSON.parse(putText || '{}'); } catch {}
    if (!putRes.ok) {
      return jsonResponse({ ok: false, error: 'GitHub contents upload failed', status: putRes.status, detail: (putJson.message || putText || '').slice(0, 300) }, 502);
    }

    // Optional notification issue (small metadata only)
    let issueUrl = null;
    try {
      const counts = data.counts || {};
      const issueRes = await fetch(`https://api.github.com/repos/${repo}/issues`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Accept': 'application/vnd.github+json',
          'User-Agent': 'spms-training-share',
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          title: `[training-data] inbox upload ${ym} ${sha.slice(0, 8)}`.slice(0, 120),
          labels: (env.TRAINING_GITHUB_LABELS || 'training-data,inbox').split(',').map(s => s.trim()).filter(Boolean).slice(0, 10),
          body: [
            '## Opt-in training data upload (sanitized)',
            '',
            `- Created: ${now.toISOString()}`,
            `- Repo path: \`${path}\``,
            `- Package sha256: \`${data.sha256 || 'n/a'}\``,
            `- Size: ${data.size_bytes || raw.length} bytes`,
            `- Counts: ${JSON.stringify(counts)}`,
            '',
            '> Uploaded by SPMS app after explicit user opt-in. Review/sanitize before training use.',
          ].join('\n').slice(0, 60000),
        }),
      });
      if (issueRes.ok) {
        const issue = await issueRes.json();
        issueUrl = issue.html_url || null;
      }
    } catch {}

    return jsonResponse({
      ok: true,
      path,
      content_url: putJson.content?.html_url || null,
      commit_sha: putJson.commit?.sha || null,
      issue_url: issueUrl,
    });
  } catch (e) {
    return jsonResponse({ ok: false, error: 'Unexpected server error.' }, 500);
  }
}

export async function onRequest(context) {
  return jsonResponse({ ok: false, error: 'Method not allowed. Use POST.' }, 405);
}
