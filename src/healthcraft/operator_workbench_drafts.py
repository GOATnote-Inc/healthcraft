"""Opt-in, in-memory saved-response resume for the engineering workbench.

Load ``SCRIPT`` after the unchanged v2 form script. It installs
``globalThis.HealthcraftDrafts`` with ``preview(text)``, ``apply()``, ``cancel()``,
``undo()`` and detached ``state()``. Preview accepts only full, ordered v2 exports
that can round-trip exactly through the existing form serializer. Unsupported
manual shapes reject before form mutation. The original packet/template globals
and field IDs remain authoritative; no judgment, timer, persistence or network
operation is added.

In this new view only, a capture-phase Add finding listener seeds the unchanged
v2 allocator from current IDs before every click. Large saved IDs remain exact;
new IDs use the first unused small suffix instead of overflowing a Number.

Optional controls (all or none): ``draft-file`` file input; ``draft-preview``,
``draft-apply``, ``draft-cancel``, ``draft-undo`` buttons; ``draft-status`` text
container. Preview never applies a file. Undo restores the preceding raw form,
including malformed textarea strings and the original finding nodes/listeners.
"""

SCRIPT = r"""
(()=>{
  'use strict';
  const isAdjudication=
    packet.schema_version==='healthcraft-operator-incident-adjudication-packet/v2';
  let pending=null,
  previous=null,
  generation=0;
  const own=(v,
  k)=>Object.prototype.hasOwnProperty.call(v,
  k);
  function requireDraft(ok,
  message){
    if(!ok)throw new Error(message);
  }
  function stable(value){
    if(Array.isArray(value))return '['+value.map(stable).join(',')+']';
    if(value!==null&&typeof value==='object')return '{'+Object.keys(value).sort()
      .map(k=>JSON.stringify(k)+':'+stable(value[k])).join(',')+'}';
    return JSON.stringify(value);
  }
  function decimal(token){
    const m=token.match(/^(-?)(\d+)(?:\.(\d+))?(?:[eE]([+-]?\d+))?$/);
    let digits=(m[2]+(m[3]||'')).replace(/^0+/,
    '');
    if(!digits)return '0';
    let exponent=BigInt(m[4]||'0')-BigInt((m[3]||'').length);
    const zeroes=digits.length-digits.replace(/0+$/,
    '').length;
    digits=digits.slice(0,
    digits.length-zeroes);
    exponent+=BigInt(zeroes);
    return m[1]+digits+'e'+exponent;
  }
  function exactNumbers(raw){
    const stringToken=/"(?:[^"\\\u0000-\u001f]|\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))*"/;
    const numberToken=/-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/;
    const tokens=raw.match(new RegExp(stringToken.source+'|'+numberToken.source,'g'))||[];
    for(const token of tokens){
      if(token[0]==='"')continue;
      const value=Number(token);
      requireDraft(Number.isFinite(value)&&(!Number.isInteger(value)||Number.isSafeInteger(value))&&
      decimal(token)===decimal(String(value)),
      'Numeric input cannot be represented exactly by this form; file was not applied.');
    }
  }
  function display(value){
    return value===null?'':value;
  }
  function utf8Strings(value){
    if(typeof value==='string'){
      for(const character of value){
        const point=character.codePointAt(0);
        requireDraft(point<0xd800||point>0xdfff,
          'Unpaired Unicode surrogate cannot be exported as a valid UTF-8 response.');
      }
    }else if(Array.isArray(value)){
      value.forEach(utf8Strings);
    }else if(value!==null&&typeof value==='object'){
      for(const [key,child]of Object.entries(value)){
        utf8Strings(key);utf8Strings(child);
      }
    }
  }
  function encoded(value){
    return JSON.stringify(value);
  }
  function judgment(row){
    const result={
      judgment:display(row.judgment),
      unassessed_reason:display(row.unassessed_reason),
      rationale:row.rationale,
      evidence_refs:encoded(row.evidence_refs)
    }
    ;
    if(isAdjudication)result.response_pointers=encoded(row.response_pointers);
    return result;
  }
  function formValue(value){
    const result={
      cases:value.cases.map(row=>{
        if(isAdjudication)return {
          checks:row.checks.map(judgment),
          overall:display(row.overall),
          unassessed_reason:display(row.unassessed_reason),
          rationale:row.rationale
        }
        ;
        const t=row.identified_target,
        a=row.incident_assessment,
        time=row.timing;
        return {
          identified_target:{
            status:display(t.status),
            patient_id:t.patient_id,
            encounter_id:t.encounter_id,
            unassessed_reason:display(t.unassessed_reason),
            rationale:t.rationale,
            evidence_refs:encoded(t.evidence_refs)
          }
          ,
          axes:row.axes.map(judgment),
          incident_assessment:{
            status:display(a.status),
            summary:a.summary,
            unassessed_reason:display(a.unassessed_reason),
            evidence_refs:encoded(a.evidence_refs),
            findings:a.findings.map(f=>({
              finding_id:f.finding_id,
              category:f.category,
              claim:f.claim,
              observed_target:{
                patient_id:display(f.observed_target.patient_id),
                encounter_id:display(f.observed_target.encounter_id)
              }
              ,
              source_ids:encoded(f.source_ids),
              evidence_refs:encoded(f.evidence_refs)
            }
            ))
          }
          ,
          timing:{
            method:time.method,
            elapsed_seconds:time.elapsed_seconds===null?'':String(time.elapsed_seconds),
            active_seconds:time.active_seconds===null?'':String(time.active_seconds),
            note:time.note
          }
        }
        ;
      }
      )
    }
    ;
    if(isAdjudication){
      const d=value.reviewer_declaration;
      result.reviewer_declaration={
        independent_review:d.independent_review===null?'':String(d.independent_review),
        qualifications:d.qualifications,
        conflicts:d.conflicts
      }
      ;
    }
    return result;
  }
  function validate(raw){
    const value=strictJSON(raw);
    exactNumbers(raw);
    utf8Strings(value);
    requireDraft(value!==null&&typeof value==='object'&&!Array.isArray(value),
    'Saved response must be an object.');
    for(const key of Object.keys(responseTemplate)
      .filter(k=>k!=='cases'&&k!=='reviewer_declaration'))
    requireDraft(own(value,
    key)&&stable(value[key])===stable(responseTemplate[key]),
    'Saved response '+key+' differs from this assignment.');
    requireDraft(Array.isArray(value.cases)&&value.cases.length===responseTemplate.cases.length,
    'Full assigned case roster is required.');
    const input=formValue(value);
    const rebuilt=isAdjudication?buildAdjudicationResponse(input,
    responseTemplate,
    packet):buildIncidentResponse(input,
    responseTemplate,
    packet);
    requireDraft(stable(rebuilt)===stable(value),
    'Unsupported saved response shape, field, order or value; no data may be discarded.');
    return {
      response:value,
      input
    }
    ;
  }
  function element(id){
    const node=document.getElementById(id);
    requireDraft(node!==null,
    'Form control unavailable: '+id);
    return node;
  }
  function checkControl(node,
  value){
    requireDraft(typeof value==='string',
    'Saved field cannot be represented as text.');
    if(node.tagName==='SELECT')requireDraft(Array.from(node.options).some(o=>o.value===value),
    'Saved choice is unavailable in this form.');
  }
  function plan(input){
    const fields=[],
    containers=[];
    const counters={
      ...findingCounters
    }
    ;
    function field(id,
    value){
      const node=element(id);
      checkControl(node,
      value);
      fields.push({
        node,
        value
      }
      );
    }
    function check(prefix,
    value){
      field(prefix+'-judgment',
      value.judgment);
      field(prefix+'-reason',
      value.unassessed_reason);
      field(prefix+'-rationale',
      value.rationale);
      field(prefix+'-refs',
      value.evidence_refs);
      if(isAdjudication)field(prefix+'-response-pointers',
      value.response_pointers);
    }
    input.cases.forEach((row,
    ci)=>{
      const p='case-'+ci;
      if(isAdjudication){
        row.checks.forEach((v,
        i)=>check(p+'-check-'+i,
        v));
        field(p+'-overall',
        row.overall);
        field(p+'-overall-reason',
        row.unassessed_reason);
        field(p+'-overall-rationale',
        row.rationale);
      }
      else{
        const t=row.identified_target,
        a=row.incident_assessment;
        for(const [suffix,
        value] of Object.entries({
          status:t.status,
          patient:t.patient_id,
          encounter:t.encounter_id,
          reason:t.unassessed_reason,
          rationale:t.rationale,
          refs:t.evidence_refs
        }
        ))field(p+'-target-'+suffix,
        value);
        row.axes.forEach((v,
        i)=>check(p+'-axis-'+i,
        v));
        for(const [suffix,
        value]of Object.entries({
          status:a.status,
          reason:a.unassessed_reason,
          summary:a.summary,
          refs:a.evidence_refs
        }
        ))field(p+'-incident-'+suffix,
        value);
        const container=element('findings-'+ci),
        template=element('finding-template-'+ci);
        const nodes=a.findings.map(f=>{
          const fragment=template.content.cloneNode(true),
          node=fragment.querySelector('[data-finding]');
          requireDraft(node!==null,
          'Finding template unavailable.');
          const values={
            finding_id:f.finding_id,
            category:f.category,
            claim:f.claim,
            patient_id:f.observed_target.patient_id,
            encounter_id:f.observed_target.encounter_id,
            source_ids:f.source_ids,
            evidence_refs:f.evidence_refs
          }
          ;
          for(const [name,
          value] of Object.entries(values)){
            const control=node.querySelector('[data-field="'+name+'"]');
            requireDraft(control!==null,
            'Finding field unavailable: '+name);
            checkControl(control,
            value);
            control.value=value;
          }
          const remove=node.querySelector('[data-remove-finding]');
          requireDraft(remove!==null,
          'Finding remove control unavailable.');
          remove.addEventListener('click',
          ()=>node.remove());
          const match=f.finding_id.match(/^finding-(\d+)$/i);
          if(match&&Number.isSafeInteger(Number(match[1])))counters[ci]=Math.max(counters[ci]||0,
          Number(match[1]));
          return node;
        }
        );
        containers.push({
          node:container,
          nodes
        }
        );
        for(const [key,
        value] of Object.entries(row.timing))field(p+'-timing-'+key,
        value);
      }
    }
    );
    if(isAdjudication){
      const d=input.reviewer_declaration;
      field('declaration-independent',
      d.independent_review);
      field('declaration-qualifications',
      d.qualifications);
      field('declaration-conflicts',
      d.conflicts);
    }
    return {
      fields,
      containers,
      counters
    }
    ;
  }
  function counterValues(values){
    for(const key of Object.keys(findingCounters))delete findingCounters[key];
    Object.assign(findingCounters,
    values);
  }
  function capture(operation){
    return {
      fields:operation.fields.map(({
        node
      }
      )=>({
        node,
        value:node.value
      }
      )),
      containers:operation.containers.map(({
        node
      }
      )=>({
        node,
        nodes:Array.from(node.childNodes)
      }
      )),
      counters:{
        ...findingCounters
      }
    }
    ;
  }
  function write(operation){
    for(const {
      node,
      value
    }
    of operation.fields)node.value=value;
    for(const {
      node,
      nodes
    }
    of operation.containers)node.replaceChildren(...nodes);
    counterValues(operation.counters);
  }
  function state(){
    return {
      pending:pending!==null,
      can_undo:previous!==null,
      mode:isAdjudication?'adjudication':'incident',
      case_count:responseTemplate.cases.length
    }
    ;
  }
  function preview(raw){
    generation++;
    pending=null;
    const valid=validate(raw);
    plan(valid.input);
    pending=valid;
    return state();
  }
  function apply(){
    requireDraft(pending!==null,
    'Preview a valid saved response before applying.');
    const valid=validate(JSON.stringify(pending.response)),
    operation=plan(valid.input),
    old=capture(operation);
    try{
      write(operation);
    }
    catch(error){
      write(old);
      throw error;
    }
    previous=old;
    pending=null;
    generation++;
    return state();
  }
  function cancel(){
    pending=null;
    generation++;
    return state();
  }
  function undo(){
    requireDraft(previous!==null,
    'There is no applied file to undo.');
    const old=previous,
    current=capture(old);
    try{
      write(old);
    }
    catch(error){
      write(current);
      throw error;
    }
    previous=null;
    pending=null;
    generation++;
    return state();
  }
  globalThis.HealthcraftDrafts=Object.freeze({
    preview,
    apply,
    cancel,
    undo,
    state
  }
  );
  for(const button of document.querySelectorAll('[data-add-finding]')){
    button.addEventListener('click',()=>{
      const ci=button.dataset.addFinding;
      const used=new Set(Array.from(element('findings-'+ci)
        .querySelectorAll('[data-finding]')).map(node=>
          node.querySelector('[data-field="finding_id"]').value.toLowerCase()));
      let suffix=1;
      while(used.has('finding-'+suffix))suffix++;
      // The first gap is at most the number of displayed findings plus one.
      findingCounters[ci]=suffix-1;
    },true);
  }
  const names=['draft-file',
  'draft-preview',
  'draft-apply',
  'draft-cancel',
  'draft-undo',
  'draft-status'];
  const controls=names.map(name=>document.getElementById(name));
  if(controls.some(Boolean)){
    requireDraft(controls.every(Boolean),
    'Saved-response controls must be provided together.');
    const [file,
    previewButton,
    applyButton,
    cancelButton,
    undoButton,
    status]=controls;
    function update(message){
      status.textContent=message;
      applyButton.disabled=pending===null;
      cancelButton.disabled=pending===null;
      undoButton.disabled=previous===null;
    }
    file.addEventListener('change',
    ()=>{
      cancel();
      update('File selected. Preview validates it before any form change.');
    }
    );
    previewButton.addEventListener('click',
    async()=>{
      pending=null;
      const ticket=++generation;
      try{
        requireDraft(file.files&&file.files.length===1,
        'Choose one saved response JSON file.');
        const raw=await file.files[0].text();
        if(ticket!==generation)return;
        const valid=validate(raw);
        plan(valid.input);
        pending=valid;
        const result=state();
        update('Preview validated '+result.case_count+
          ' assigned case(s). Apply to replace the form, or Cancel. '+
          'No judgments were inferred.');
      }
      catch(error){
        if(ticket!==generation)return;
        update('Not applied: '+error.message+' Current form entries are unchanged.');
      }
    }
    );
    for(const [button,
    action,
    message]of [[applyButton,
    apply,
    'Applied saved response. Undo restores your previous raw entries.'],
    [cancelButton,
    cancel,
    'Preview cancelled; current form entries are unchanged.'],
    [undoButton,
    undo,
    'Previous raw form entries restored.']])button.addEventListener('click',
    ()=>{
      try{
        action();
        update(message);
      }
      catch(error){
        update('Not changed: '+error.message);
      }
    }
    );
    update('Choose a saved v2 response, then Preview. No autosave or network access is used.');
  }
}
)();
"""
