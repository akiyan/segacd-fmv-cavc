import {useEffect, useRef, useState} from 'react';

const ExternalLink = ({href, children}) => <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>;

export function Licenses() {
  const dialog = useRef(null);
  const [notices, setNotices] = useState(null);
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(false);
  const request = useRef(null);
  useEffect(() => () => request.current?.abort(), []);

  async function open() {
    dialog.current.showModal();
    if (notices || loading) return;
    const controller = new AbortController();
    request.current = controller;
    setLoading(true);
    setError(false);
    try {
      const response = await fetch(`${import.meta.env.BASE_URL}licenses/notices.json`, {signal: controller.signal});
      if (!response.ok) throw new Error('License notices unavailable');
      setNotices(await response.json());
    } catch (error) {
      if (error.name !== 'AbortError') setError(true);
    } finally {
      setLoading(false);
    }
  }

  return <>
    <button type="button" className="footer-licenses" onClick={open}>Licenses</button>
    <dialog ref={dialog} className="licenses-dialog" aria-labelledby="licenses-heading"
      onClick={event => {if (event.target === event.currentTarget) dialog.current.close();}}>
      <div className="licenses-panel">
        <header className="licenses-header">
          <h2 id="licenses-heading">Licenses &amp; source code</h2>
          <button type="button" autoFocus onClick={() => dialog.current.close()}>Close</button>
        </header>
        <div className="licenses-content" tabIndex={0}>
          <p>SEGA-CD FMV Encoder for CAVC uses the open-source software listed below. Third-party components retain their own licenses.</p>
          <p><ExternalLink href="https://github.com/akiyan/segacd-fmv-cavc">Project source code on GitHub</ExternalLink></p>
          {loading && <p role="status">Loading license notices…</p>}
          {error && <p role="alert">License notices could not be loaded. <button type="button" onClick={open}>Retry</button></p>}
          {notices?.map(entry => <section className="license-entry" key={entry.name}>
            <div className="license-heading"><h3>{entry.name}{entry.version ? ` ${entry.version}` : ''}</h3><span>{entry.license}</span></div>
            {entry.note && <p>{entry.note}</p>}
            <div className="license-links">{entry.links.map(link => <ExternalLink key={link.href} href={link.href}>{link.label}</ExternalLink>)}</div>
            {entry.texts.map(text => <details key={text.name}><summary>{text.name}</summary><pre>{text.text}</pre></details>)}
          </section>)}
        </div>
      </div>
    </dialog>
  </>;
}
