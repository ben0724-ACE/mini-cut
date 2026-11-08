export type SaveState="dirty"|"saving"|undefined;
export function SaveStatus({dirty=false,saving=false,failed=false}:{dirty?:boolean;saving?:boolean;failed?:boolean}){
  const text=failed?"未保存":saving?"保存中":dirty?"未保存":"";
  return text?<span className="edit-tab-unsaved" role="status">{text}</span>:null;
}
