export interface ExportLocationEntry {outputId:string;taskId:string}

function locationUrl(project:string,collection:string,entries:ExportLocationEntry[]) {
  const query=new URLSearchParams({project,view:"exports",collection});
  for(const entry of entries){query.append("output",entry.outputId);query.append("task",entry.taskId);}
  return `${window.location.pathname}?${query}`;
}

function notifyNavigation(){window.dispatchEvent(new PopStateEvent("popstate"));}

export function navigateToExportResults(project:string,collection:string,entries:ExportLocationEntry[]) {
  window.history.pushState({},"",locationUrl(project,collection,entries));
  notifyNavigation();
}

export function replaceExportResults(project:string,collection:string,entries:ExportLocationEntry[]) {
  window.history.replaceState({},"",locationUrl(project,collection,entries));
  notifyNavigation();
}
