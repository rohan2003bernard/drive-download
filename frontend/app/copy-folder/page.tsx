'use client';

import { useState, type FormEvent } from 'react';

export default function CopyFolderPage() {
  const [link, setLink] = useState('');
  const [targetPath, setTargetPath] = useState('');
  const [status, setStatus] = useState('');
  const [progress, setProgress] = useState(0);
  const [responseJson, setResponseJson] = useState('');

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setStatus('');
    setProgress(0);
    setResponseJson('');

    if (!link.trim()) {
      setStatus('Please enter a Google Drive folder link or ID.');
      return;
    }

    setStatus('Copying folder...');
    setProgress(10);
    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'https://dork-egotism-alive.ngrok-free.dev';
      const response = await fetch(`${apiUrl}/api/copy-folder`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ link, target_path: targetPath.trim() || undefined }),
      });

      setProgress(60);
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        setStatus('Copy failed: ' + (data.detail || data.error || response.statusText));
        setResponseJson(JSON.stringify(data, null, 2));
        return;
      }

      setProgress(100);
      setStatus(`Saved ${data.files?.length || 0} file(s) to ${data.output_directory || targetPath || 'the target folder'}.`);
      setResponseJson(JSON.stringify(data, null, 2));
    } catch (err) {
      setStatus('Request error: ' + (err instanceof Error ? err.message : String(err)));
    }
  };

  return (
    <main style={{ padding: '24px', background: '#f4f5f7', minHeight: '100vh' }}>
      <div style={{ maxWidth: 640, margin: '0 auto', background: '#fff', padding: 24, borderRadius: 12, boxShadow: '0 2px 12px rgba(0,0,0,.08)' }}>
        <h1>Copy Drive Folder</h1>
        <p style={{ marginBottom: 16, padding: 12, borderRadius: 8, background: '#e2e8f0' }}>
          Enter a Google Drive folder link or ID. The server will prepare the files and you will choose a folder on your device to save them.
        </p>

        <form onSubmit={handleSubmit}>
          <input
            type="text"
            value={link}
            onChange={(event) => setLink(event.target.value)}
            placeholder="https://drive.google.com/drive/folders/..."
            style={{ width: '100%', padding: 12, marginBottom: 16, borderRadius: 6, border: '1px solid #cbd5e1' }}
          />
          <input
            type="text"
            value={targetPath}
            onChange={(event) => setTargetPath(event.target.value)}
            placeholder="C:\\Users\\Name\\Downloads\\MyFolder"
            style={{ width: '100%', padding: 12, marginBottom: 16, borderRadius: 6, border: '1px solid #cbd5e1' }}
          />
          <button type="submit" style={{ background: '#0366d6', color: '#fff', border: 'none', padding: '12px 18px', borderRadius: 6, cursor: 'pointer' }}>
            Copy Folder
          </button>
        </form>

        <div style={{ marginTop: 16 }}>
          <strong>Status:</strong> {status}
        </div>
        <div style={{ marginTop: 12, width: '100%', background: '#e2e8f0', borderRadius: 999, overflow: 'hidden', height: 12 }}>
          <div style={{ width: `${progress}%`, height: '100%', background: '#0366d6', transition: 'width 0.3s ease' }} />
        </div>

        {responseJson && (
          <pre style={{ background: '#f1f5f9', padding: 16, overflow: 'auto', borderRadius: 8, marginTop: 16 }}>
            {responseJson}
          </pre>
        )}
      </div>
    </main>
  );
}
