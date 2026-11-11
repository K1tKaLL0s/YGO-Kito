const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const root = String.raw`E:\CodexData\2026-11-01\task\role-training-v7`;
const out = path.join(root, 'semantic_audit');
const inputPath = path.join(root, 'goal_intake.json');
const inputBytes = fs.readFileSync(inputPath);
const source = JSON.parse(inputBytes.toString('utf8').replace(/^\uFEFF/, ''));
// These quote boundaries were chosen while only goal_intake.json was available.
// They are source-text boundaries, never selections inferred from roles or case families.
const initialQuotes = [
 '以杀手级调整曲同调持续控场',
 '以卡通怪兽攻击取胜',
 '以杀手级调整曲同调持续换取场面',
 '以反复通常召唤阿莱斯特、融合梅尔卡巴、回收阿莱斯特的循环取得场面优势，靠该循环的无效与攻击取胜',
 '以光与暗的仪式、黑混沌仪式怪兽及仪式资源循环取得优势，之后让仪式怪兽从手卡或墓地回卡组特召超魔剑士黑混沌，用除外及攻击终结',
 '以阿莱斯特的梅尔卡巴融合循环控场取胜；阿莱斯特通常召唤后依次连接独角兔、安全守卫者，以墓地阿莱斯特与场上光属性守卫者融合，回收阿莱斯特并以已备同类手牌回应发动。',
 '以召唤兽和幻兽融合的场面优势取胜',
 '以阿不思相关连续融合、冰剑龙除外及送墓后的结束阶段资源取得长期优势；通过导化、气炎、烙印融合与圣女衔接，在后续回合回收烙印魔陷和融合素材。',
 '以阿不思融合体系反复建立冰剑龙等融合怪兽，结合墓地、除外和烙印魔陷回收，在较长资源交换中获胜；用白之烙印、赫之烙印、圣女及其它融合支路延续行动。',
 '以星辰融合怪兽完成攻击与场面交换',
 '围绕暗黑都市取得命运英雄、恶魔主宰人送墓并取得场地、无惧从者破坏场地叫出恐惧人，再转为无惧人检索与后续英雄融合，以凤凰人破坏循环和英雄攻击获胜。',
 '以命运英雄场地破坏、检索和融合循环组织进攻，同时用影雾女郎、暮鸦、炉火衔接假面变化及不同英雄额外怪兽，按本回合属性和召唤限制建立英雄终端后持续攻击。',
 '以恐惧人、无惧人、凤凰人的循环交换取胜',
 '以破械连接怪兽持续交换对方场面',
 '以破械连接怪兽交换场面',
 '以再世高星怪兽与后续资源取胜',
 '以额外融合和连接怪兽接续展开获胜',
 '本局围绕天底送墓旧神取得教导圣女、圣女衔接骑士无效，后续回合再利用教导怪兽，并以教导攻击时的全体增攻逐步获胜',
 '以烙印连续融合取得长期优势',
 '以卡通攻击获胜',
 '以闪刀魔法和连接循环取得资源',
 '以灵摆和指示物怪兽继续展开',
 '以恩底弥翁和魔导兽积累、转移、支付魔力指示物，由仆从从灵摆区带出怪兽，建立创圣魔导王、胡狼王持续无效，再以灵摆资源与怪兽攻击获胜。',
 '以龙王绝火琐罗亚等魔法师融合怪兽和连接节点交换场面；统辖取得侍女或皇国，皇国取得雷古勒斯，展示另一魔法师特召并取得魔法；玻璃在发动过魔法后登场，杰妮把魔法师换成其它魔女术，继续取得后续行动的魔法师。',
 '以七音服与龙剑士的灵摆资源转为后续连接进攻',
 '以巳剑仪式怪兽与仪式循环取胜',
 '以急袭猛禽升阶建立大型超量怪兽',
 '以相剑同调怪兽持续进攻',
 '以超重和相剑同调接续展开',
 '以闪刀魔法和连接循环取胜',
 '以栗子球防守资源延长对局，再进入额外怪兽进攻',
 '以闪刀魔法和闪刀姬循环交换取胜：零衣进入额外区，交闪检索、燎里回收、雫空结束阶段取得魔法，双纽回收，再以连接怪兽与抓锚处理场面',
 '以栗球兽卫、光与暗的仪式和黑混沌仪式怪兽的魔法回收建立资源，之后将仪式怪兽回卡组特召超魔剑士黑混沌，以其除外和攻击终结',
 '以味美喵及其它连接节点进入后续场面',
 '以味美喵和其它连接怪兽维持场面',
 '以捕食植物融合怪兽和后续场面交换获胜',
 '以蜂兰蝎叫出眼镜蛇、取得超融合，将场上两只暗属性捕食植物融合为凶饿毒融合龙，作为本局主要进攻路线',
 '以捕食融合怪兽推进场面',
 '以卡通怪兽和后续连接进攻获胜',
 '以烙印融合和墓地资源取得长期优势'
];
const bfOrc1 = '本次取胜计划是靠自奏圣乐的墓地、除外区和连接怪兽反复交换资源，建立通天塔下的对手回合响应，用丁吉尔苏等处理对手场面，再以机械怪兽继续进攻。';
const bfOrc2 = '本次取胜计划是让三幻魔怪兽持续站场并战斗；希望在本轮所需的非暗属性特殊召唤全部完成后，再通过自奏圣乐取得一轮墓地响应和后续资源，使三幻魔场面被处理后仍可继续行动。下一回合重新安排召唤顺序；不在暗属性限制已生效后要求特殊召唤非暗怪兽。';
const terms = [
 ['杀手级调整曲','terminal','synchro'], ['卡通怪兽','actor','monster'], ['卡通','actor',null],
 ['阿莱斯特','actor','monster'], ['梅尔卡巴','terminal','fusion'], ['光与暗的仪式','actor','spell'],
 ['黑混沌仪式怪兽','actor','ritual'], ['超魔剑士黑混沌','terminal','monster'],
 ['独角兔','actor','link'], ['安全守卫者','actor','link'], ['召唤兽','actor','fusion'], ['幻兽','actor',null],
 ['阿不思','actor','monster'], ['冰剑龙','terminal','fusion'], ['导化','actor','monster'], ['气炎','actor','spell'],
 ['烙印融合','actor','spell'], ['白之烙印','actor','spell'], ['赫之烙印','actor','spell'], ['圣女','actor','monster'],
 ['烙印魔陷','resource',null], ['烙印','actor',null], ['星辰融合怪兽','terminal','fusion'], ['星辰','actor',null], ['暗黑都市','actor','spell'],
 ['命运英雄','actor','monster'], ['恶魔主宰人','actor','monster'], ['无惧从者','actor','monster'],
 ['恐惧人','actor','monster'], ['无惧人','actor','monster'], ['凤凰人','terminal','fusion'],
 ['影雾女郎','actor','monster'], ['暮鸦','actor','monster'], ['炉火','actor','monster'], ['假面变化','actor','spell'],
 ['破械连接怪兽','actor','link'], ['再世高星怪兽','actor','monster'], ['天底','actor','spell'],
 ['旧神','resource','fusion'], ['教导圣女','actor','monster'], ['骑士','actor','monster'], ['教导怪兽','actor','monster'],
 ['闪刀魔法','actor','spell'], ['恩底弥翁','actor',null], ['魔导兽','actor','monster'],
 ['仆从','actor','monster'], ['创圣魔导王','terminal','monster'], ['胡狼王','terminal','monster'],
 ['龙王绝火琐罗亚','terminal','fusion'], ['统辖','actor','spell'], ['侍女','actor','monster'],
 ['皇国','actor','spell'], ['雷古勒斯','actor','monster'], ['玻璃','actor','monster'], ['杰妮','actor','monster'],
 ['魔女术','actor',null], ['七音服','actor',null], ['龙剑士','actor',null], ['巳剑仪式怪兽','actor','ritual'],
 ['急袭猛禽','actor',null], ['相剑同调怪兽','terminal','synchro'], ['相剑','actor',null], ['超重','actor',null],
 ['栗子球','resource','monster'], ['闪刀姬','actor',null], ['零衣','actor','monster'], ['交闪','actor','spell'],
 ['燎里','actor','link'], ['雫空','actor','link'], ['双纽','actor','spell'], ['抓锚','actor','spell'],
 ['栗球兽卫','actor','monster'], ['味美喵','actor','link'], ['捕食植物融合怪兽','terminal','fusion'],
 ['捕食融合怪兽','terminal','fusion'], ['蜂兰蝎','actor','monster'], ['眼镜蛇','actor','monster'],
 ['超融合','actor','spell'], ['凶饿毒融合龙','terminal','fusion'], ['暗属性捕食植物','resource','monster'],
 ['鲜花女男爵','terminal','synchro'], ['装弹枪管狞猛龙','terminal','synchro'], ['圣天树','actor',null],
 ['圣蔓','actor',null], ['S：P小夜骑士','terminal','link'], ['刻魔融合怪兽','terminal','fusion'],
 ['破械怪兽','actor','monster'], ['无垢大艺术','actor',null], ['狱神使','actor',null], ['三幻魔','actor','monster'],
 ['炎王怪兽','actor','monster'], ['大鹏不死鸟','terminal','monster'], ['朱罗纪','actor','monster'],
 ['圣炎王','actor','monster'], ['凤凰不死鸟','actor','monster'],
 ['麒麟','actor','monster'], ['青眼','actor','monster'], ['原石','actor',null], ['神碑速攻魔法','actor','spell'],
 ['神碑之泉','actor','spell'], ['混沌战士','terminal','ritual'], ['黑混沌','terminal','ritual'],
 ['光与暗仪式怪兽','terminal','ritual'],
 ['混沌怪兽','terminal','monster'], ['僵尸牧人','actor','monster'], ['坏兽','actor','monster'],
 ['京塔','actor','spell'], ['出现记录','actor','spell'], ['荷鲁斯','actor','monster'], ['阎摩','actor','link'],
 ['萨巴拉','actor','monster'], ['唱导','resource','trap'], ['阿罗汉','resource','monster'],
 ['邪恶双子姬丝基勒','actor','link'], ['璃拉','actor','link'], ['邪恶双子','actor',null],
 ['来迎','terminal','link'], ['一瓣','actor','monster'], ['来来','actor','spell'], ['叶牡丹','actor','monster'],
 ['绚烂','actor','spell'], ['白姬','actor','monster'], ['六花超量终端','terminal','xyz'],
 ['圣种之地灵','actor','monster'], ['圣蔓的播种','actor','spell'], ['芳香','actor',null],
 ['自奏圣乐','actor',null], ['通天塔','actor','spell'], ['丁吉尔苏','terminal','xyz']
];
function entitiesFor(text) {
 const found = [];
 const sorted = terms.map((t,order)=>({t,order})).sort((a,b)=>b.t[0].length-a.t[0].length);
 const intervals = [];
 for (const {t,order} of sorted) {
  const [surface,kind,type_constraint] = t;
  let start = text.indexOf(surface);
  if (start < 0) continue;
  if (intervals.some(([a,b])=>start>=a && start+surface.length<=b)) continue;
  const sentenceStart = Math.max(text.lastIndexOf('；',start),text.lastIndexOf('。',start),text.lastIndexOf('：',start))+1;
  let sentenceEnd = text.slice(start).search(/[；。]/);
  sentenceEnd = sentenceEnd < 0 ? text.length : start+sentenceEnd;
  const actionKind = surface==='阿莱斯特' && text.slice(Math.max(0,start-2),start)==='回收' ? 'resource' : kind;
  found.push({surface,kind:actionKind,name_contains:surface,type_constraint,evidence_quote:text.slice(sentenceStart,sentenceEnd),_order:order,_start:start});
  intervals.push([start,start+surface.length]);
 }
 return found.sort((a,b)=>a._start-b._start).map(({_order,_start,...e})=>e);
}
function tagsFor(t) {
 const tags=[]; const add=(tag,re)=>{if(re.test(t))tags.push(tag)};
 add('fusion',/融合/);add('link',/连接/);add('synchro',/同调/);add('ritual',/仪式/);
 add('search',/检索|搜索|调度|取得命运英雄|取得侍女|取得雷古勒斯|取得场地|取得魔法|取得教导圣女|取得超融合/);
 add('special_summon',/特召|特殊召唤|复活|回场|叫出|带出|招募/);add('negate',/无效/);add('destroy',/破坏|清场/);
 add('draw',/抽牌|抽卡|无法抽卡/);add('recover',/回收|复活|恢复|回场/);add('grave',/送墓|墓地/);
 add('banish',/除外/);add('spell_counter',/魔力指示物|指示物怪兽/);add('pendulum',/灵摆/);add('transformation',/假面变化|形态转换/);
 add('attack',/攻击|进攻|战斗/);add('xyz',/超量|8阶/);add('normal_summon',/通常召唤/);
 add('additional_normal_summon',/追加通常召唤|额外通常召唤|多进行一次通常召唤/);add('tribute',/解放/);
 return tags;
}
const rows=source.map((r,i)=>{
 let q=null;
 if(i<40) q=initialQuotes[i];
 else if(r.objective_primary_quote) q=r.objective_primary_quote;
 else if(r.objective.startsWith('反事实主计划')) {
  const suffix=r.objective.slice(r.objective.indexOf('：')+1);
  const stops=['查询','本次','额外查询'].map(s=>suffix.indexOf(s)).filter(x=>x>=0);
  q=suffix.slice(0,Math.min(...stops)).replace(/[；。\s]+$/,'');
 } else if(r.case_id==='BF-ORC-01') q=bfOrc1;
 else if(r.case_id==='BF-ORC-02') q=bfOrc2;
 if(q!==null && !r.objective.includes(q))throw new Error('Quote mismatch '+r.case_id);
 const unknown=[];
 if(q===null) unknown.push('未声明独立于本次局部功能查询的主策略/取胜计划；不能从焦点功能、选组或卡数量反推核心与支援。');
 if(q && /其它|等怪兽|后续场面|接续展开获胜|继续展开|再世高星|超重和相剑|星辰融合怪兽|捕食融合怪兽|卡通|杀手级调整曲|破械连接怪兽|烙印连续融合/.test(q)) unknown.push('主计划有明确机制/方向，但未逐一指名全部终端或组织路径；仅保留原文明确命名的实体。');
 if(q && r.case_id==='dogmatika_extra_order_conflict') unknown.push('额外融合与连接主计划未指名具体怪兽；不把后段天底、旧神与圣女作为主计划实体。');
 if(q && /以灵摆和指示物怪兽继续展开/.test(q)) unknown.push('未指名任何主计划卡片/系列；只有灵摆与指示物操作方向。');
 const e=q?entitiesFor(q):[];
 // No attribute of the current selected group is consulted here.
 return {case_id:r.case_id,primary_plan_text:q,evidence_quote:q??r.objective,confidence:q?'high':'unknown',operation_tags:q?tagsFor(q):[],entities:e,unknown_information:unknown,...(q===null?{declared_local_goal_text:r.objective,scope_note:'局部功能目标已保留，但没有据此补写全局主计划。'}:{})};
});
if(rows.length!==118 || new Set(rows.map(r=>r.case_id)).size!==118)throw new Error('Expected 118 unique inputs');
for(const r of rows)for(const e of r.entities){if(!r.primary_plan_text.includes(e.surface)||!r.primary_plan_text.includes(e.evidence_quote))throw new Error('Entity lacks primary quote '+r.case_id)}
const primary={schema_version:'semantic-primary-plans-v1',phase:'1-goal-only',source:'../goal_intake.json',source_sha256:crypto.createHash('sha256').update(inputBytes).digest('hex'),row_count:rows.length,role_labels_read_before_freeze:false,definition:'主计划依据原始 objective 的明确声明；保留明确起动链和资源组织，不把本次查询/准备动作自动提升为主计划。实体 kind 仅描述原文动作位置，不表示 core/support。',unknown_primary_plan_case_count:rows.filter(r=>r.primary_plan_text===null).length,cases:rows};
fs.writeFileSync(path.join(out,'primary_plans.json'),JSON.stringify(primary,null,2)+'\n','utf8');
console.log(JSON.stringify({phase:'draft_written',rows:rows.length,unknown_primary_plan_cases:primary.unknown_primary_plan_case_count,entity_count:rows.reduce((s,r)=>s+r.entities.length,0)}));
