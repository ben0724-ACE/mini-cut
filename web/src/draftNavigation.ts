let guard:((proceed:()=>void)=>void)|undefined;
export function registerDraftGuard(value:(proceed:()=>void)=>void){guard=value;return()=>{if(guard===value)guard=undefined;};}
export function navigateWithDraft(proceed:()=>void){if(guard)guard(proceed);else proceed();}
