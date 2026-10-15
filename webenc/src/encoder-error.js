export function encoderErrorNotice(message) {
 const text=String(message);
 const python=[...text.matchAll(/^\s*((?:[A-Za-z_][\w.]*Error|SystemExit|KeyboardInterrupt):[^\n]*)$/gm)].at(-1);
 const summary=python?.[1]||text.split('\n').find(line=>line.trim())||'Encoding failed';
 return `${summary.trim().slice(0,280)}${summary.length>280?'…':''} See Activity log for details.`;
}
