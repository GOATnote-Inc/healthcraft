"""Additional offline workbench; the original v2 issuer and reports stay unchanged.

Sources are materialized only when requested. A lossless navigation parser keeps
number lexemes separate from JavaScript Number so displayed facts never inherit
JSON.parse rounding. This is not a browser performance or usability validation.
"""

from __future__ import annotations

from html import escape

from healthcraft import operator_incident_report as v2

_SOURCE_SCRIPT = r"""
"use strict";
(function () {
  const PAGE_SIZE = 50;
  let sourceTree = null;
  const decodedCache = new Map();
  function fail(message) { throw new Error(message); }
  function ensure(test, message) { if (!test) fail(message); }
  function pointerToken(value) { return value.replace(/~/g,"~0").replace(/\//g,"~1"); }
  function unicode(value) {
    for (let i=0;i<value.length;i++) {
      const c=value.charCodeAt(i);
      if (c>=0xd800 && c<=0xdbff) {
        const next=value.charCodeAt(++i);
        ensure(next>=0xdc00 && next<=0xdfff,"Unpaired Unicode surrogate.");
      } else ensure(c<0xdc00 || c>0xdfff,"Unpaired Unicode surrogate.");
    }
    return value;
  }
  function parseLossless(text) {
    ensure(typeof text==="string","JSON source must be text.");
    let pos=0;
    function space() { while (/[\x20\t\r\n]/.test(text[pos]||"x")) pos++; }
    function string() {
      ensure(text[pos]==='"',"Expected JSON string.");
      const start=pos++;
      while (pos<text.length) {
        const c=text[pos++];
        if (c==='"') return unicode(JSON.parse(text.slice(start,pos)));
        if (c==='\\') pos++;
      }
      fail("Unterminated JSON string.");
    }
    function value() {
      space();const c=text[pos];
      if (c==='"') return {kind:"string",value:string()};
      if (c==='{' || c==='[') {
        const object=c==='{', end=object?'}':']', children=[], keys=new Set();pos++;space();
        if (text[pos]===end) {pos++;return {kind:object?"object":"array",children};}
        while (true) {
          let key=String(children.length);
          if (object) {
            key=string();ensure(!keys.has(key),"Duplicate JSON key: "+key);keys.add(key);
            space();ensure(text[pos++]===':',"Expected JSON colon.");
          }
          children.push({key,node:value()});space();
          if (text[pos]===end) {pos++;break;}
          ensure(text[pos++]===',',"Expected JSON separator.");space();
        }
        return {kind:object?"object":"array",children};
      }
      for (const literal of ["true","false","null"]) {
        if (text.slice(pos,pos+literal.length)===literal) {
          pos+=literal.length;return {kind:literal==="null"?"null":"boolean",raw:literal};
        }
      }
      const number=text.slice(pos).match(/^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/);
      ensure(number!==null,"Invalid JSON value.");
      const raw=number[0];
      // Integer tokens remain strings: arbitrary Python integers must not overflow Number.
      if (/[.eE]/.test(raw)) ensure(Number.isFinite(Number(raw)),"Nonfinite JSON number.");
      pos+=raw.length;return {kind:"number",raw};
    }
    const result=value();space();ensure(pos===text.length,"Unexpected trailing JSON text.");
    return result;
  }
  function resolveNode(node,pointer) {
    ensure(validPointer(pointer),"Invalid RFC6901 pointer.");
    if (pointer==="") return node;
    for (const token of pointer.slice(1).split("/")) {
      const key=token.replace(/~1/g,"/").replace(/~0/g,"~");
      ensure(node.kind==="object" || node.kind==="array","Source scalar has no children.");
      if (node.kind==="array") {
        ensure(/^(0|[1-9][0-9]*)$/.test(key) && String(Number(key))===key,
          "Invalid array index.");
      }
      const child=node.children.find(item=>item.key===key);
      ensure(child!==undefined,"Source pointer unavailable.");node=child.node;
    }
    return node;
  }
  function cloneRef(ref) { return JSON.parse(JSON.stringify(ref)); }
  function childRef(ref,key) {
    const result=cloneRef(ref), field=Object.hasOwn(ref,"decoded_json_pointer")?
      "decoded_json_pointer":"pointer";
    result[field]+="/"+pointerToken(key);return result;
  }
  function parentRef(ref) {
    const result=cloneRef(ref), decoded=Object.hasOwn(ref,"decoded_json_pointer");
    const field=decoded?"decoded_json_pointer":"pointer";
    if (result[field]==="") {
      if (decoded) {delete result.decoded_json_pointer;return result;}
      return null;
    }
    result[field]=result[field].slice(0,result[field].lastIndexOf("/"));return result;
  }
  function inspect(caseIndex,reference,offset=0) {
    ensure(Number.isInteger(caseIndex) && caseIndex>=0 && caseIndex<packet.cases.length,
      "Unknown assigned case.");
    ensure(reference && typeof reference==="object" && !Array.isArray(reference),
      "Reference must be an object.");
    const keys=Object.keys(reference);
    ensure(keys.includes("document") && keys.includes("pointer") && keys.every(key=>
      ["document","pointer","decoded_json_pointer"].includes(key)),"Unexpected reference fields.");
    const ref=cloneRef(reference), docs=packet.cases[caseIndex].documents;
    ensure(typeof ref.document==="string" && Object.hasOwn(docs,ref.document),
      "Unknown source document.");
    ensure(ref.document!=="response" || !Object.hasOwn(ref,"decoded_json_pointer"),
      "Response references cannot decode JSON; cite the exact raw response pointer.");
    ensure(validPointer(ref.pointer) && (!Object.hasOwn(ref,"decoded_json_pointer") ||
      validPointer(ref.decoded_json_pointer)),"Invalid RFC6901 pointer.");
    ensure(Number.isInteger(offset) && offset>=0,"Invalid child page offset.");
    const base={reference:ref,status:"available",reason:null,display:null,raw_text:null,
      children:[],total_children:0,offset,page_size:PAGE_SIZE,parent_reference:parentRef(ref)};
    if (docs[ref.document]===null) {
      return {...base,status:"unavailable",kind:null,reason:
        packet.cases[caseIndex].availability?.[ref.document]?.reason ||
        "No captured document was supplied."};
    }
    if (sourceTree===null) {
      sourceTree=parseLossless(document.getElementById("incident-packet").textContent);
    }
    let node;
    try {
      node=resolveNode(sourceTree,"/cases/"+caseIndex+"/documents/"+pointerToken(ref.document));
      node=resolveNode(node,ref.pointer);
    } catch (error) {return {...base,status:"unavailable",kind:null,reason:error.message};}
    if (Object.hasOwn(ref,"decoded_json_pointer")) {
      ensure(node.kind==="string","Decoded reference must address captured text.");
      base.raw_text=node.value;
      const cacheKey=JSON.stringify([caseIndex,ref.document,ref.pointer]);
      try {
        if (!decodedCache.has(cacheKey)) decodedCache.set(cacheKey,parseLossless(node.value));
        node=resolveNode(decodedCache.get(cacheKey),ref.decoded_json_pointer);
      } catch (error) {
        return {...base,status:"unavailable",kind:null,
          reason:"Decoded JSON unavailable: "+error.message};
      }
    }
    base.kind=node.kind;
    if (node.kind==="object" || node.kind==="array") {
      base.total_children=node.children.length;
      ensure(offset<=node.children.length,"Child page starts beyond the available source.");
      base.children=node.children.slice(offset,offset+PAGE_SIZE).map(child=>({
        label:child.key,kind:child.node.kind,reference:childRef(ref,child.key)}));
    } else base.display=node.kind==="string"?node.value:node.raw;
    return base;
  }
  function element(tag,text) {
    const item=document.createElement(tag);if(text!==undefined)item.textContent=text;return item;
  }
  function action(text,callback) {
    const button=element("button",text);button.type="button";
    button.addEventListener("click",callback);return button;
  }
  function clearInspection(caseIndex) {
    const prefix="source-"+caseIndex;
    document.getElementById(prefix+"-children").replaceChildren();
    document.getElementById(prefix+"-context").replaceChildren();
    document.getElementById(prefix+"-value").textContent="";
    document.getElementById(prefix+"-raw").textContent="";
    document.getElementById(prefix+"-citation").value="";
    document.getElementById(prefix+"-raw-container").hidden=true;
  }
  function open(caseIndex,ref,offset=0) {
    const prefix="source-"+caseIndex, status=document.getElementById(prefix+"-status");
    const children=document.getElementById(prefix+"-children");
    const value=document.getElementById(prefix+"-value");
    const raw=document.getElementById(prefix+"-raw");
    const context=document.getElementById(prefix+"-context");
    clearInspection(caseIndex);
    try {
      const result=inspect(caseIndex,ref,offset);
      document.getElementById(prefix+"-query").value=JSON.stringify(result.reference);
      const citation=result.reference.document==="response"?
        JSON.stringify(result.reference.pointer):JSON.stringify(result.reference);
      document.getElementById(prefix+"-citation").value=
        result.status==="available"?citation:"";
      document.getElementById(prefix+"-citation-label").textContent=
        result.reference.document==="response"?"Copy into response_pointers array":
        "Copy into evidence_refs array";
      status.textContent=result.status==="available"?"Exact captured "+result.kind:
        "Unavailable: "+result.reason;
      value.textContent=result.display===null?"":result.display;
      raw.textContent=result.raw_text===null?"":result.raw_text;
      document.getElementById(prefix+"-raw-container").hidden=result.raw_text===null;
      if (result.parent_reference) context.appendChild(action("Parent context",()=>
        open(caseIndex,result.parent_reference)));
      if (result.kind==="string" && !Object.hasOwn(ref,"decoded_json_pointer") &&
          ref.document!=="response") context.appendChild(action("Inspect as strict JSON",()=>
            open(caseIndex,{...ref,decoded_json_pointer:""})));
      if (result.status==="available" && ["object","array"].includes(result.kind)) {
        const end=Math.min(offset+PAGE_SIZE,result.total_children);
        context.appendChild(element("p",`Children ${offset===end?0:offset+1}–${end} of `+
          result.total_children+". All source children remain available."));
        if(offset>0) context.appendChild(action("Previous children",()=>
          open(caseIndex,ref,Math.max(0,offset-PAGE_SIZE))));
        if(end<result.total_children) context.appendChild(action("Next children",()=>
          open(caseIndex,ref,end)));
        for(const child of result.children) {
          const li=element("li");li.appendChild(action(child.label+" · "+child.kind,()=>
            open(caseIndex,child.reference)));children.appendChild(li);
        }
      }
      return result;
    } catch(error) {
      status.textContent="Unavailable: "+error.message;
      document.getElementById(prefix+"-citation").value="";
      document.getElementById(prefix+"-raw-container").hidden=true;
      return {status:"unavailable",reason:error.message};
    }
  }
  for(const button of document.querySelectorAll("[data-source-document]")) {
    button.addEventListener("click",()=>open(Number(button.dataset.case),{
      document:button.dataset.sourceDocument,pointer:""}));
  }
  for(const link of document.querySelectorAll("[data-source-ref]")) {
    link.addEventListener("click",()=>open(Number(link.dataset.case),
      strictJSON(link.dataset.sourceRef)));
  }
  for(const button of document.querySelectorAll("[data-source-open]")) {
    button.addEventListener("click",()=>{
      const index=Number(button.dataset.sourceOpen);
      try {open(index,strictJSON(document.getElementById("source-"+index+"-query").value));}
      catch(error){
        clearInspection(index);
        document.getElementById("source-"+index+"-status").textContent=
          "Unavailable: "+error.message;
      }
    });
  }
  for(const button of document.querySelectorAll("[data-source-copy]")) {
    button.addEventListener("click",()=>{
      const input=document.getElementById("source-"+button.dataset.sourceCopy+"-citation");
      input.focus();input.select();
      if(typeof navigator!=="undefined" && navigator.clipboard) {
        navigator.clipboard.writeText(input.value).catch(()=>{});
      }
    });
  }
  globalThis.HealthcraftSources=Object.freeze({inspect,open});
})();
"""


def _inspector(case: dict, index: int) -> str:
    prefix = f"source-{index}"
    content = (
        f'<section class="sources" id="source-inspector-{index}">'
        "<h2>Inspect captured sources</h2><p>Open a document or paste an exact reference. "
        "Only the requested branch is displayed; no source facts are discarded. "
        "A real null differs from an unavailable document.</p><nav>"
    )
    for name in (*v2._DOCUMENTS, "response", "prior_judgments"):
        if name not in case["documents"]:
            continue
        content += (
            f'<button type="button" data-case="{index}" '
            f'data-source-document="{escape(name, quote=True)}">'
            f"{escape(name.replace('_', ' ').title())}</button>"
        )
    reference = '{"document":"task","pointer":""}'
    content += (
        "</nav><label>Exact source reference (JSON object)"
        f'<textarea id="{prefix}-query" rows="2">{escape(reference)}</textarea></label>'
        f'<button type="button" data-source-open="{index}">Open reference</button>'
        f'<p id="{prefix}-status" role="status">No source selected.</p>'
        f'<div id="{prefix}-context"></div><ul id="{prefix}-children"></ul>'
        f'<pre id="{prefix}-value" class="literal"></pre>'
        f'<details id="{prefix}-raw-container" hidden><summary>Raw captured JSON text</summary>'
        f'<pre id="{prefix}-raw" class="literal"></pre></details>'
        f'<label><span id="{prefix}-citation-label">Copy into evidence_refs array</span>'
        f'<input id="{prefix}-citation" readonly value=""></label>'
        f'<button type="button" data-source-copy="{index}">Copy / select citation</button>'
        "<p>The citation is also selectable for manual copying. For an absent field, "
        "cite its existing parent and explain the absence.</p></section>"
    )
    return content


def _assistance(case: dict, index: int) -> str:
    from healthcraft.operator_incidents import validate_incident_references

    assistance = case["assistance"]
    if assistance is None:
        return (
            '<section class="assistance"><h2>Derived assistance</h2><p>Unavailable.</p></section>'
        )
    v2._require(
        assistance.get("schema_version") == "healthcraft-incident-evidence/v1"
        and assistance.get("document_sha256")
        == {key: v2._digest(case["documents"][key]) for key in v2._DOCUMENTS},
        "Assistance document binding mismatch",
    )
    content = (
        '<section class="assistance"><h2>Derived assistance — claims to inspect</h2>'
        "<p>These are source-linked observations, not your answers or clinical conclusions. "
        f"Availability: {escape(assistance['status'])}.</p>"
    )
    for claim in assistance["claims"]:
        validate_incident_references(claim["refs"], case["documents"])
        content += (
            '<article class="claim"><h3>'
            + escape(claim["category"] + ": " + claim["summary"])
            + "</h3><p><code>"
            + escape(claim["code"])
            + "</code></p><details><summary>Recorded values</summary><pre>"
            + v2._pretty(claim["observed"])
            + "</pre></details><ul>"
        )
        for ref in claim["refs"]:
            # The issuing packet already binds recomputed assistance. References remain exact.
            encoded = v2._json(ref)
            content += (
                f'<li><a href="#source-inspector-{index}" data-case="{index}" '
                f'data-source-ref="{escape(encoded, quote=True)}">'
                f"{escape(encoded)}</a></li>"
            )
        content += "</ul></article>"
    content += "<h3>Coverage and limitations</h3><pre>" + v2._pretty(assistance["coverage"])
    content += (
        "</pre><ul>"
        + "".join("<li>" + escape(item) + "</li>" for item in assistance["limitations"])
        + "</ul><p>Unassessed: "
        + escape(v2._json(assistance["unassessed"]))
        + "</p></section>"
    )
    return content


def render_workbench(packet: dict, template: dict) -> str:
    """Render an additional view, keeping original v2 response identities unchanged."""
    from healthcraft.operator_workbench_drafts import SCRIPT as draft_script

    v2._require(type(packet) is dict, "Packet must be an object")
    adjudication = packet.get("schema_version") == (
        "healthcraft-operator-incident-adjudication-packet/v2"
    )
    cases, definitions = v2._validate(packet, template, adjudication)
    title = "Operator incident workbench" if not adjudication else "Report validity workbench"
    content = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{title}</title><style>{v2._STYLE}</style></head><body><main><header>"
        f"<h1>{title}</h1><p>Additional offline view of the original assignment. "
        "Captured evidence, assistance and independent judgments remain separate. "
        "No clinical validation, automatic truth or measured timing is produced.</p>"
        f"<p>Assignment <code>{escape(packet['assignment_id'])}</code></p><nav><ul>"
    )
    for index, case in enumerate(cases):
        content += f'<li><a href="#case-{index}">{escape(case["review_case_id"])}</a></li>'
    content += (
        "</ul></nav><ul>"
        + "".join("<li>" + escape(item) + "</li>" for item in packet["limitations"])
        + "</ul></header>"
    )
    content += (
        '<section class="response"><h2>Resume an exported response</h2>'
        "<p>Preview a local response, then explicitly apply it. A foreign or malformed "
        "response must not replace current work. No automatic browser storage or timer runs.</p>"
        '<label>Exported response JSON<input id="draft-file" type="file" '
        'accept="application/json,.json"></label>'
        '<button type="button" id="draft-preview">Preview response</button>'
        '<button type="button" id="draft-apply">Apply preview</button>'
        '<button type="button" id="draft-cancel">Cancel preview</button>'
        '<button type="button" id="draft-undo">Undo last apply</button>'
        '<p id="draft-status" role="status">No saved response loaded.</p></section>'
    )
    for index, case in enumerate(cases):
        family = (
            "Unknown — not captured"
            if case["scenario_family_id"] is None
            else case["scenario_family_id"]
        )
        content += (
            f'<article class="case" id="case-{index}"><h2>{escape(case["review_case_id"])}</h2>'
            f"<p>Scenario family: <code>{escape(family)}</code></p>"
        )
        content += _inspector(case, index)
        if adjudication:
            content += (
                "<p>Operator report completeness: "
                + escape(case["operator_report_status"])
                + ".</p>"
            )
            content += v2._adjudication_form(case, definitions, index)
        else:
            if packet["presentation"] == "assisted":
                content += _assistance(case, index)
            content += v2._incident_form(case, definitions, index)
        content += "</article>"
    if adjudication:
        content += (
            '<section class="response"><h2>Reviewer declaration</h2>'
            "<p>Self-reported declarations do not establish identity or independence.</p>"
            + v2._label(
                "Independent review declaration",
                v2._select(
                    "declaration-independent", [("true", "Yes, self-declared"), ("false", "No")]
                ),
            )
            + v2._label("Qualifications (self-reported)", v2._area("declaration-qualifications"))
            + v2._label("Conflicts (self-reported)", v2._area("declaration-conflicts"))
            + "</section>"
        )
    content += (
        '<section class="export"><button type="button" id="download-response">'
        'Export response JSON</button><p id="export-status" role="status">'
        "Save before closing. Pending fields stay pending. This export uses the original "
        "assignment identity and v2 response schema.</p></section>"
        '<script id="incident-packet" type="application/json">'
        + v2._embedded(packet)
        + '</script><script id="incident-template" type="application/json">'
        + v2._embedded(template)
        + '</script><script id="incident-app">'
        + v2._SCRIPT
        + '</script><script id="workbench-sources">'
        + _SOURCE_SCRIPT
        + '</script><script id="workbench-drafts">'
        + draft_script
        + "</script></main></body></html>"
    )
    return content
