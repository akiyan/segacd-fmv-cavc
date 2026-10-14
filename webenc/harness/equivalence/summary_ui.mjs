import {chromium,expect} from '@playwright/test';
import {readFile} from 'node:fs/promises';
import {spawn} from 'node:child_process';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const job=process.argv[2];if(!job)throw new Error('Completed Wasm summary fixture required');
const repo=fileURLToPath(new URL('../../../',import.meta.url));
const summary=JSON.parse(await readFile(path.join(job,'summary-fixture/encode-summary.json'),'utf8'));
const manager=spawn(path.join(repo,'tools/python.sh'),['--gpu',path.join(repo,'webenc/harness/equivalence/lease.py'),job],{stdio:['pipe','pipe','inherit']});await new Promise(resolve=>manager.stdout.once('data',resolve));
const browser=await chromium.launch({headless:true});
try {
 const page=await browser.newPage({viewport:{width:900,height:700}});
 await page.goto('http://127.0.0.1:4173');await expect(page.getByRole('button',{name:'Choose source video',exact:true})).toBeVisible();
 await page.evaluate(async summary=>{
  const {default:React}=await import('/node_modules/.vite/deps/react.js');
  const {default:client}=await import('/node_modules/.vite/deps/react-dom_client.js');
  const {EncodeSummary}=await import('/src/EncodeSummary.jsx');
  document.body.innerHTML='<style>.encode-summary-body{height:auto;max-height:none}</style><div id="fixture" style="width:100%;padding:16px"></div>';
  client.createRoot(document.querySelector('#fixture')).render(React.createElement(EncodeSummary,{summary,status:'complete',onSeek:frame=>window.inspectedFrame=frame,seekDisabled:false}));
 },summary);
 await expect(page.getByLabel('Encoder decisions')).toContainText(`${summary.paletteSets.length} palette sets`);
 await expect(page.getByLabel('Encoder decisions')).toContainText('Stream verified');
 const colorIndex=summary.paletteSets[0].colors[0].findIndex(rgb=>rgb.some(value=>value>0));
 if(colorIndex>=0){const display=summary.paletteSets[0].colors[0][colorIndex].map(value=>value*36);expect(await page.locator('.palette-swatch').nth(colorIndex+1).evaluate(el=>getComputedStyle(el).backgroundColor)).toBe(`rgb(${display.join(', ')})`);}
 await page.screenshot({path:path.join(job,'summary-fixture/palette-overview.png')});
 await expect(page.getByRole('button',{name:'Palettes',exact:true})).toHaveCount(0);
 await expect(page.getByRole('button',{name:'Overview',exact:true})).toHaveCount(0);
 await expect(page.getByRole('button',{name:'Events',exact:true})).toHaveCount(0);
 expect(await page.locator('.palette-set-list article').count()).toBe(summary.paletteSets.length);
 expect(await page.locator('.palette-swatch').count()).toBe(summary.paletteSets.length*4*16);
 const order=await page.evaluate(()=>{const rect=s=>document.querySelector(s).getBoundingClientRect();return {palettes:rect('.palette-set-list').bottom,timeline:rect('.summary-effect-overview').top,timelineEnd:rect('.summary-effect-overview').bottom,events:rect('.encode-event-list').top};});
 const codec=page.getByLabel('Codec timeline',{exact:true});
 await expect(codec.getByRole('img')).toBeVisible();
 expect(await page.evaluate(()=>document.querySelector('.codec-timeline').getBoundingClientRect().bottom<=document.querySelector('.palette-set-list').getBoundingClientRect().top)).toBe(true);
 const plot=codec.getByRole('img'),rect=await plot.boundingBox();
 await plot.evaluate((element,frames)=>element.addEventListener('click',event=>{window.expectedTimelineFrame=Math.floor((event.clientX-element.getBoundingClientRect().left)/element.getBoundingClientRect().width*frames);}),summary.frames);
 await plot.click({position:{x:rect.width*.5,y:10}});
 expect(await page.evaluate(()=>window.inspectedFrame)).toBe(await page.evaluate(()=>window.expectedTimelineFrame));
 await page.getByRole('button',{name:'Detail',exact:true}).click();
 expect(await page.locator('.codec-timeline-viewport').evaluate(element=>element.scrollWidth>element.clientWidth)).toBe(true);
 await plot.click({position:{x:21,y:10}});expect(await page.evaluate(()=>window.inspectedFrame)).toBe(10);
 await page.getByRole('button',{name:'Detail',exact:true}).click();
 expect(order.timeline).toBeGreaterThanOrEqual(order.palettes);expect(order.events).toBeGreaterThanOrEqual(order.timelineEnd);
 expect(await page.locator('.encode-event-list button').count()).toBe(summary.scroll.length+summary.fades.length);
 if(summary.scroll.length){await page.getByRole('button',{name:new RegExp(summary.scroll[0].axis==='x'?'Horizontal scroll':'Vertical scroll')}).first().click();expect(await page.evaluate(()=>window.inspectedFrame)).toBe(summary.scroll[0].start);}
 for(const event of summary.fades)await expect(page.getByLabel('Encoder decisions')).toContainText(`${event.controls} CRAM writes`);
 await page.screenshot({path:path.join(job,'summary-fixture/combined-summary.png'),fullPage:true});
 for(const width of [600,390]){await page.setViewportSize({width,height:900});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);}
 const wraps=await page.locator('.palette-set-card').evaluateAll(cards=>new Set(cards.map(card=>Math.round(card.getBoundingClientRect().top))).size);expect(wraps).toBeGreaterThan(1);
 console.log('PASS: unified wrapping palette cards, effect timeline, chronological events and exact seek targets from qualified Lunar decisions');
}finally{await browser.close();manager.stdin.end();}
