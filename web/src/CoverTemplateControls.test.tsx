import {useState} from "react";
import {beforeEach,expect,it,vi} from "vitest";
import {fireEvent,render,screen,waitFor} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {CoverTemplateControls} from "./CoverTemplateControls";
import * as api from "./coverApi";
import type {CoverDesign,CoverTemplate} from "./coverApi";
vi.mock("./coverApi",async original=>({...await original<typeof import("./coverApi")>(),listCoverTemplates:vi.fn(),writeCoverTemplate:vi.fn(),renameCoverTemplate:vi.fn(),deleteCoverTemplate:vi.fn(),applyCoverTemplate:vi.fn()}));
const design:CoverDesign={mode:"design",aspect_ratio:"9:16",background_color:"#172033",background_image:null,background_scale:1,background_x:.5,background_y:.5,frame_ms:1500,frame:{x:.08,y:.14,width:.84,height:.46},frame_fit:"contain",title:"自己的封面文字",title_box:{x:.08,y:.66,width:.84,height:.25},font_id:null,font_size:88,bold:true,text_color:"#ffffff",stroke_color:"#000000",stroke_width:0,align:"center"};
const {title:_title,frame_ms:_frame,...style}=design;
const template:CoverTemplate={template_id:"cover-template-one",name:"深色访谈",style:{...style,font_size:120},created_at:"now",updated_at:"now"};
let templates:CoverTemplate[]=[];
const busy=vi.fn();
function Harness(){const [value,setValue]=useState(design);return <><CoverTemplateControls project="p" collection="c" output="o" revision={1} design={value} onChange={setValue} disabled={false} onBusy={busy}/><output aria-label="当前设计">{JSON.stringify(value)}</output><button onClick={()=>setValue({...value,font_size:66})}>调整当前字号</button></>;}
beforeEach(()=>{vi.clearAllMocks();templates=[structuredClone(template)];vi.mocked(api.listCoverTemplates).mockImplementation(async()=>structuredClone(templates));vi.mocked(api.applyCoverTemplate).mockImplementation(async(_route,_revision,id,_mode,current)=>({...current,font_size:120,template_id:id,template_name:"深色访谈"}));vi.mocked(api.writeCoverTemplate).mockImplementation(async(name,source,id)=>{const record={...template,template_id:id??"cover-template-new",name,style:{...style,font_size:source.design.font_size}};templates=[...templates.filter(item=>item.template_id!==record.template_id),record];return record;});vi.mocked(api.renameCoverTemplate).mockImplementation(async(id,name)=>{const record={...template,template_id:id,name};templates=templates.map(item=>item.template_id===id?record:item);return record;});vi.mocked(api.deleteCoverTemplate).mockImplementation(async id=>{templates=templates.filter(item=>item.template_id!==id);});});
it("选择不应用，显式应用后才能用当前配置更新模板",async()=>{
  render(<Harness/>);await screen.findByRole("option",{name:"深色访谈"});
  fireEvent.change(screen.getByLabelText("封面模板"),{target:{value:template.template_id}});
  expect(api.applyCoverTemplate).not.toHaveBeenCalled();expect(screen.getByLabelText("当前设计")).toHaveTextContent('"font_size":88');
  expect(screen.getByText("用当前配置更新模板")).toBeDisabled();
  fireEvent.click(screen.getByText("仅标题样式"));await waitFor(()=>expect(api.applyCoverTemplate).toHaveBeenCalledWith(expect.any(String),1,template.template_id,"title",expect.objectContaining({title:design.title,frame_ms:1500})));
  await waitFor(()=>expect(screen.getByText("用当前配置更新模板")).toBeEnabled());
  expect(screen.getByLabelText("当前设计")).toHaveTextContent('"title":"自己的封面文字"');
  fireEvent.click(screen.getByText("调整当前字号"));expect(api.writeCoverTemplate).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("用当前配置更新模板"));await waitFor(()=>expect(api.writeCoverTemplate).toHaveBeenCalledWith(template.name,expect.objectContaining({design:expect.objectContaining({font_size:66})}),template.template_id));
});
it("另存、重命名、删除与提示词预设管理流程一致，删除保留当前设计",async()=>{
  const user=userEvent.setup();render(<Harness/>);await screen.findByRole("option",{name:"深色访谈"});
  await user.click(screen.getByText("管理我的封面模板"));
  await user.type(screen.getByLabelText("封面模板名称"),"新模板");await user.click(screen.getByText("另存为模板"));
  await screen.findByRole("option",{name:"新模板"});
  expect(screen.getByLabelText("当前设计")).toHaveTextContent('"template_id":"cover-template-new"');
  await waitFor(()=>{expect(screen.getByLabelText("封面模板名称")).toBeEnabled();expect(screen.getByLabelText("封面模板名称")).toHaveValue("新模板");expect(screen.getByLabelText("封面模板")).toHaveValue("cover-template-new");});
  await user.clear(screen.getByLabelText("封面模板名称"));await user.type(screen.getByLabelText("封面模板名称"),"改名模板");await user.click(screen.getByText("重命名模板"));
  await screen.findByRole("option",{name:"改名模板"});await waitFor(()=>expect(screen.getByText("删除模板")).toBeEnabled());
  fireEvent.click(screen.getByText("删除模板"));expect(api.deleteCoverTemplate).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("确认删除模板"));await waitFor(()=>expect(api.deleteCoverTemplate).toHaveBeenCalledWith("cover-template-new"));
  await screen.findByText(/原模板已删除或未找到/);
  expect(screen.getByLabelText("当前设计")).toHaveTextContent('"font_size":88');
  expect(screen.getByLabelText("当前设计")).toHaveTextContent('"title":"自己的封面文字"');
});
it("应用失败保留原设计，并允许再次尝试",async()=>{
  vi.mocked(api.applyCoverTemplate).mockRejectedValueOnce(new Error("字体不可用"));
  render(<Harness/>);await screen.findByRole("option",{name:"深色访谈"});
  fireEvent.change(screen.getByLabelText("封面模板"),{target:{value:template.template_id}});fireEvent.click(screen.getByText("全部设计"));
  await screen.findByText("字体不可用");expect(screen.getByLabelText("当前设计")).toHaveTextContent('"font_size":88');
  fireEvent.click(screen.getByText("全部设计"));await waitFor(()=>expect(screen.getByLabelText("当前设计")).toHaveTextContent('"font_size":120'));
});
