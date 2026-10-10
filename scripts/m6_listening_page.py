# ruff: noqa: E501
"""M6: build the local blind listening page from the loudness-matched A/B excerpts.

    cd server && uv run python ../scripts/m4_6_compare.py --out data/m4_6      # renders the audio (git-ignored)
    cd server && uv run python ../scripts/m6_listening_page.py [--root data/m4_6]
    open server/data/m4_6/listening/index.html     # works from file://, no network, no server

The page shows, per set (Natural / Urban / Hybrid), the Legacy / Organic / Composed excerpt under neutral labels
(X, Y, Z) in a per-set shuffled order, all matched to the same integrated loudness. Ratings (1-5) are saved in the browser
and exported as CSV that includes the key, so you can read the result after rating. No rating is ever pre-filled.
The audio derives from ESC-50 clips (CC BY-NC 3.0): keep it local, never publish it.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

SETS = {"natural": "Natural", "urban": "Urban", "hybrid": "Hybrid"}
MODES = ("legacy", "organic", "composed")
CRITERIA = [
    (
        "coherence",
        "Musical coherence",
        "Does it sound like one piece with a shape, not a pile of sounds?",
    ),
    (
        "rhythm",
        "Rhythm and variation",
        "Is there a pulse or flow, and does it change in interesting ways?",
    ),
    ("clarity", "Sound clarity", "Can you hear distinct layers without mud or harshness?"),
    (
        "recognizability",
        "Source recognizability",
        "Can you still tell the real-world sounds it was made from?",
    ),
    ("emotion", "Emotional impact", "Does it make you feel something (any feeling)?"),
    ("enjoyment", "Overall listening enjoyment", "Would you willingly listen to it again?"),
]


def find_excerpt(root: Path, set_key: str, mode: str) -> Path | None:
    hits = sorted((root / "AB").glob(f"*{set_key}*_{mode}.wav"))
    hits = [h for h in hits if "groove" not in h.name]
    return hits[0] if hits else None


def build(root: Path, seed: int) -> Path:
    rng = random.Random(seed)
    sets = []
    for key, title in SETS.items():
        files = {m: find_excerpt(root, key, m) for m in MODES}
        if not all(files.values()):
            raise SystemExit(
                f"missing excerpts for set '{key}' under {root / 'AB'}; run m4_6_compare.py first"
            )
        order = list(MODES)
        rng.shuffle(order)
        sets.append(
            {
                "key": key,
                "title": title,
                "clips": [
                    {"label": "XYZ"[i], "mode": m, "src": f"../AB/{files[m].name}"}  # type: ignore[union-attr]
                    for i, m in enumerate(order)
                ],
            }
        )
    out = root / "listening"
    out.mkdir(parents=True, exist_ok=True)
    page = PAGE.replace("__DATA__", json.dumps({"sets": sets, "criteria": CRITERIA, "seed": seed}))
    path = out / "index.html"
    path.write_text(page, encoding="utf-8")
    return path


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Blind listening review</title>
<style>
:root{--bg:#f6f4ef;--fg:#1c1b19;--mut:#6b675f;--card:#fff;--line:#d9d4c8;--acc:#2b5d6e}
@media (prefers-color-scheme:dark){:root{--bg:#121416;--fg:#ecebe6;--mut:#9a978f;--card:#1b1e21;--line:#33383c;--acc:#7fb7c9}}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,sans-serif}
main{max-width:860px;margin:0 auto;padding:16px}
h1{font-size:1.4rem}h2{font-size:1.15rem;margin:0 0 8px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px;margin:16px 0}
.clip{border-top:1px solid var(--line);padding:12px 0}
.clip:first-of-type{border-top:0}
audio{width:100%}
.row{display:grid;grid-template-columns:1fr auto;gap:8px;align-items:center;margin:6px 0}
.row small{color:var(--mut);display:block}
.scale{display:flex;gap:4px}
.scale label{display:inline-flex}
.scale input{position:absolute;opacity:0}
.scale span{min-width:34px;min-height:34px;display:grid;place-items:center;border:1px solid var(--line);border-radius:6px;cursor:pointer}
.scale input:checked+span{background:var(--acc);color:#fff;border-color:var(--acc)}
.scale input:focus-visible+span{outline:2px solid var(--acc);outline-offset:2px}
button{font:inherit;padding:8px 14px;border-radius:8px;border:1px solid var(--line);background:var(--card);color:var(--fg);cursor:pointer}
.note{color:var(--mut);font-size:.9rem}
textarea{width:100%;box-sizing:border-box;font:inherit;background:var(--bg);color:var(--fg);border:1px solid var(--line);border-radius:6px}
@media (max-width:560px){.row{grid-template-columns:1fr}}
</style></head><body><main>
<h1>Blind listening review</h1>
<p class="note">Each set has three versions made from the same recordings, matched to the same loudness. Their order is shuffled and
the names are hidden. Use headphones once and speakers once if you can. Rate each clip 1 (poor) to 5 (excellent) after listening
to all three. Leave a criterion empty if you cannot judge it. Nothing is pre-filled and nothing is uploaded: ratings stay in this browser until you export them.</p>
<div id="sets"></div>
<div class="card"><h2>Finish</h2>
<p><label>Listening setup <select id="gear"><option value="">choose</option><option>headphones</option><option>speakers</option><option>phone speaker</option></select></label></p>
<p><button id="csv">Download ratings (CSV, includes key)</button> <button id="reset">Clear my ratings</button></p>
<p class="note" id="count"></p></div>
<script>
const DATA=__DATA__;const KEY='unheard-listening-'+DATA.seed;
let st={};try{st=JSON.parse(localStorage.getItem(KEY)||'{}')}catch(e){}
const save=()=>{try{localStorage.setItem(KEY,JSON.stringify(st))}catch(e){}count()};
const $=(t,a={},...k)=>{const e=document.createElement(t);for(const[x,v]of Object.entries(a))x==='class'?e.className=v:e.setAttribute(x,v);k.forEach(c=>e.append(c));return e};
function count(){let n=0;for(const k in st)if(/__score/.test(k)&&st[k])n++;document.getElementById('count').textContent=n+' scores recorded in this browser.'}
const root=document.getElementById('sets');
DATA.sets.forEach(s=>{
 const card=$('section',{class:'card'},$('h2',{},s.title+' set'));
 s.clips.forEach(c=>{
  const id=s.key+'-'+c.label;
  const box=$('div',{class:'clip'},$('strong',{},'Version '+c.label));
  const au=$('audio',{controls:'',preload:'none',src:c.src});box.append(au);
  DATA.criteria.forEach(([k,name,help])=>{
   const f=$('div',{class:'row'},$('div',{},name,$('small',{},help)));
   const sc=$('div',{class:'scale',role:'radiogroup','aria-label':name+' for version '+c.label});
   for(let v=1;v<=5;v++){
    const r=$('input',{type:'radio',name:id+'-'+k,value:v});
    if(st[id+'__score__'+k]==v)r.checked=true;
    r.addEventListener('change',()=>{st[id+'__score__'+k]=v;save()});
    sc.append($('label',{},r,$('span',{},String(v))));
   }
   f.append(sc);box.append(f);
  });
  card.append(box);
 });
 const fav=$('div',{class:'row'},$('div',{},'Which version did you prefer overall?'));
 const sel=$('select',{'aria-label':'preferred version in '+s.title});
 ['','X','Y','Z','no preference'].forEach(o=>sel.append($('option',{value:o},o||'choose')));
 sel.value=st[s.key+'__pref']||'';sel.addEventListener('change',()=>{st[s.key+'__pref']=sel.value;save()});
 fav.append(sel);card.append(fav);
 const ta=$('textarea',{rows:'2',placeholder:'What did you notice? (optional)','aria-label':'notes for '+s.title});
 ta.value=st[s.key+'__note']||'';ta.addEventListener('input',()=>{st[s.key+'__note']=ta.value;save()});
 card.append(ta);root.append(card);
});
document.getElementById('gear').value=st.gear||'';
document.getElementById('gear').addEventListener('change',e=>{st.gear=e.target.value;save()});
document.getElementById('reset').addEventListener('click',()=>{if(confirm('Clear all ratings in this browser?')){st={};save();location.reload()}});
document.getElementById('csv').addEventListener('click',()=>{
 const rows=[['set','version','mode_key','criterion','score','preferred_in_set','set_note','gear']];
 DATA.sets.forEach(s=>s.clips.forEach(c=>DATA.criteria.forEach(([k])=>{
  const v=st[s.key+'-'+c.label+'__score__'+k];
  rows.push([s.key,c.label,c.mode,k,v==null?'':v,st[s.key+'__pref']||'',(st[s.key+'__note']||'').replace(/[\\r\\n]+/g,' '),st.gear||'']);
 })));
 const csv=rows.map(r=>r.map(x=>'"'+String(x).replace(/"/g,'""')+'"').join(',')).join('\\n');
 const a=$('a',{href:URL.createObjectURL(new Blob([csv],{type:'text/csv'})),download:'unheard-listening-ratings.csv'});a.click();
});
count();
</script></main></body></html>
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="data/m4_6")
    ap.add_argument(
        "--seed",
        type=int,
        default=11,
        help="shuffles the blind order; kept fixed so the CSV key is reproducible",
    )
    a = ap.parse_args()
    print("wrote", build(Path(a.root), a.seed))


if __name__ == "__main__":
    main()
