const fs=require('fs'),path=require('path'),crypto=require('crypto'),assert=require('assert');
const root=String.raw`E:\CodexData\2026-11-01\task\role-training-v7`,out=path.join(root,'semantic_audit');
const read=p=>JSON.parse(fs.readFileSync(p,'utf8').replace(/^\uFEFF/,''));
const sha=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
const sourceFiles=['goal_intake.json','reference_audit_intake.json','existing_cases.json'];
const oldFiles=['primary_plans.json','PLAN_READY.json','reference_audit.json','READY.json','construction_generic_review.json','current_execution_state.json','GENERIC_READY.json','card_evidence.json','selected_scope_evidence.json','encoding_audit.json'];
const sourceHashes=sourceFiles.map(file=>({file:'../'+file,sha256:sha(path.join(root,file))}));
const protectedHashes=oldFiles.map(file=>({file,sha256:sha(path.join(out,file))}));
const refs=read(path.join(root,'reference_audit_intake.json'));
const plans=read(path.join(out,'primary_plans.json'));
const freeze=read(path.join(out,'PLAN_READY.json'));
assert.equal(sha(path.join(out,'primary_plans.json')),freeze.primary_plans_sha256);
const pmap=new Map(plans.cases.map(r=>[r.case_id,r]));
const low=refs.filter(r=>r.roles[3]!==null&&r.roles[3]<0.5);
assert.equal(low.length,44);
const N=new Map();
function add(id,category,confidence,scope,reason,basis){assert(!N.has(id));N.set(id,{category,confidence,precise_scope:scope,reason,basis});}
function primaryWhole(id,description){add(id,'supported_low',0.94,'实际 selected_main/selected_extra 的'+description+'整体，在本条明确主计划中的相对角色；不评价内部单卡/子链的支援性。','原文把这个整体的启动、资源衔接、转换及终端作用直接写成主计划本体，整体没有另被指明一个作为帮助者服务该计划的独立互补关系。这里能支持“整体相对支援匹配低”的类别：不是因被称为核心就机械排斥支援，而是按实际整体与已声明计划的关系判断；内部检索、回收、无效等能互帮，不自动广播成整组高支援。证据不确认旧零值的精确程度，也不排除未声明的其它用途。','whole_primary_organization');}
primaryWhole('invoked_artemis_cycle','阿莱斯特—召唤魔术—阿耳特弥斯—梅尔卡巴循环');
primaryWhole('invoked_almiraj_gardna','经独角兔和安全守卫者转光素材的阿莱斯特融合循环');
primaryWhole('branded_complete_40','连续融合、冰剑龙处理和结束阶段资源烙印网络');
primaryWhole('branded_complete_60','融合、墓地/除外和烙印魔陷回收网络');
primaryWhole('hero_complete_clock_destiny','场地—命运英雄—凤凰人/英雄攻击网络');
primaryWhole('hero_complete_shadow_mask','命运英雄循环与假面转换组成的英雄进攻网络');
primaryWhole('dogmatika_declared_battle_plan','天底—旧神—圣女—骑士及教导战斗组织路线');
primaryWhole('endymion_complete_spell_counters','指示物积累/支付、仆从展开、双类无效及灵摆进攻网络');
primaryWhole('striker_complete_resource_plan','闪刀检索、连接转换、回收与场面处理网络');
primaryWhole('predaplant_compact_fusion_attack','蜂兰蝎—眼镜蛇—超融合—凶饿毒主要进攻路线');
primaryWhole('v5_branded_full_with_minimum_fusion_contract','实际完整烙印选择，而不是仅附带的首段融合四件子合同');
primaryWhole('v5_hero_full_with_minimum_mask_contract','实际完整英雄选择，而不是仅附带的暮鸦变化子合同');
add('blind-v5-rn-01','supported_low',0.93,'实际完整神碑机制在“除外对方卡组、泉回收补手、最终耗尽”的明确主计划中的整体角色；不把内部抽牌或护泉节点单独抬成整组支援。','神碑速攻、泉循环和护泉正是这个整体组织耗尽主计划的本体作用，原objective没有另指明整个神碑选择服务一条独立互补安排。旧rationale补入的“陷阱控制”未在本条主计划声明，不能用它制造整组互补证据。因此整体相对低支援类别有依据；这既不否定内部资源互补，也不重新确认旧小数的程度。','whole_primary_organization');

add('v5_gamma_query_missing_driver','supported_low',0.96,'实际仅选γ，在本条杀手级调整曲同调背景及明确指定的γ响应/双体准备用途中的相对整体角色；不评价完整γ＋驱动者包。','驱动者被明确排除出精确查询，而卡文要求它参加该命名响应/双体函数。残余γ不能提供所声明的整组互补输出，原文也没有赋予它另外的独立互补用途，足以支持本作用域相对低类别。依据是结构缺必要成员，不是当前空场/手卡失败；不需要证明所有未来其它用途均无效，也不确认旧零度。','structural_required_member_missing');
add('v5_driver_query_missing_gamma','supported_low',0.95,'实际仅选驱动者，相对于原γ响应/双体函数及本条希望取得同调资源的已声明用途；不把完整骨架包的支援广播给驱动者单卡。','发动联合函数的γ被明确排除，驱动者本身不提供该响应/特召机制。它作为其它召唤素材仍可有条件价值，但原文没有在所选整体内声明另一个互补组织用途；本类别只认当前明示用途的相对低匹配，不由“当下没解放”单独推出，更不确认绝对无用或旧零值。','structural_required_member_missing');
add('v5_invoked_query_missing_aleister','supported_low',0.96,'实际召唤魔术、阿耳特弥斯和梅尔卡巴三件整体，相对于明确阿莱斯特—梅尔卡巴融合/回收主循环；不借背景阿莱斯特或改融合终端。','精确查询明确排除了梅尔卡巴指定素材及循环资源阿莱斯特，剩余三件不提供该明示主链的独立闭合互补输出。原文没有另指明这一整体的其它互补安排，因此结构上相对弱支援类别有据；这不否定这些卡在别的材料条件下的用途，也不把本次材料状态当唯一理由或确认旧零度。','structural_required_member_missing');
add('blind-v5-fs-05','supported_low',0.95,'实际仅有镇魂棺，对“解放自己从本查询实际卡组叫指定锻冶师”的明示互补用途；主背景仍为无垢形态转换。','原卡组确实未投入指定锻冶师，不是它暂时不在可用区域；该选择整体无法提供被明确查询的调度身体输出。镇魂棺装备加攻等其它潜在用途已被区分但没有在这里被声明为独立互补安排，足以支持这个限定作用域的相对低类别，无需排除所有其它未来用途，也不重申原低小数精度。','structural_required_member_missing');
add('blind-v6-uc-05','supported_low',0.85,'实际萨巴拉＋阿罗汉整体，作为邪恶双子主计划之外、明确命名的“萨巴拉—盖唱导—阿罗汉双恶魔身体”补充路线；不将已许可的一体输出抹去。','唱导在实际身份与查询中缺失，明确双体路线缺少其被破坏招募边；原文只允许破坏冥王结界波取得萨巴拉这一体，不允许补造另一招募。这个部分残余价值不等于所指定整体双体互补已成立，因此可支持相对低类别；判断承认一体仍有价值，不确认原0.0，也不要求排除其全部其它用途。','structural_required_member_missing_with_partial_value');
add('BF-ORC-04','supported_low',0.95,'只限本条已声明的“对方主要阶段骷髅复活丁吉尔苏并送墓”用途中的实际骷髅＋丁吉尔苏整体；全局主计划仍未恢复。','通天塔被明确排除出本查询，而非仅当前没在场；所指定对方回合函数缺少时点转换必要成员。两件在自己回合的潜在联系不等于该明示用途的互补输出，因此局部作用域的相对低类别有结构证据。这里不据牌表补三幻魔意图，也不确认原小数程度。','structural_required_member_missing_local_use');
add('BF-SPD-03','supported_low',0.95,'只限本条明示的“不花通常召唤取得贝陀螺＋竹蜻蜓两体”用途中的实际贝陀螺单卡；不从同家族其它条补全局取胜意图。','查询明确排除竹蜻蜓与其它疾行机人路线，所选整体不能提供要求的双体联合输出。贝陀螺的自身特召可以有残余价值，但没有被本条另行指定为独立互补安排；相对于已声明双体用途，低匹配类别有据，不等于单卡无用，也不确认旧低小数。','structural_required_member_missing_local_use');
add('BF-BRF-03','supported_low',0.96,'只限本条“明亮融合取得斜绿增加通常召唤”用途中的实际明亮融合＋尼比鲁＋斜绿整体；不借背景宝石骑士素材，也不将尼比鲁手卡响应等未声明函数纳入。','查询明确排除所有宝石骑士主卡组素材，而斜绿必须有宝石骑士素材位置，结构上缺必要部分。实际整体不提供被明示的额外通常召唤互补输出，足以支持这个局部作用域的相对低类别；不需要证明尼比鲁等卡在所有可能用途都无效，也不确认原数值程度。','structural_required_member_missing_local_use');
add('BF-BRF-04','supported_low',0.96,'只限本条“明亮融合取得斜绿增加通常召唤”用途中的实际明亮融合＋石英＋斜绿整体；不从整副牌借另一光素材。','另一只光属性素材被明确排除；石英的地属性不能满足另一光素材位置，也不能一张兼作两只融合素材。这个实际整体不能提供明示的斜绿互补输出，结构证据支持局部相对低类别。该结论不否定各成员其它用途，也不把旧低小数当作重新成立。','structural_required_member_missing_local_use');

function stateAmbiguous(id,scope,detail){add(id,'still_ambiguous',0.94,scope,detail+' 已有结论继续保留未知：这类证据只说明本次函数能否兑现，没有新增独立的整体相对支援角色类别证据。本轮不借当前失败重新归低，不要求排除所有未声明未来用途；旧数值精度也不重申。','prior_state_failure_not_reclassified');}
stateAmbiguous('gamma_occupied_field','γ＋驱动者响应整体在本条卡通攻击计划中的相对支援角色，和本连锁是否空场分开。','已有怪兽无法移走使γ当前不能响应，但单次阻断为后续行动保护这一条件性互补性质仍在。');
stateAmbiguous('tourguide_normal_already_used','导游、三眼怪、基路伯实际整体为破械连接补身体/后续资源的相对作用，和本次通常召唤次数分开。','本次通常召唤耗尽阻断入口；它没有进一步说明这条素材/资源路线相对于主破械计划为何应落入低支援类。');
stateAmbiguous('dogmatika_extra_order_conflict','天底—旧神—圣女—骑士整体的相对支援角色；给定先天底后额外的机械冲突仍按原条件单独记录。','同回合顺序与额外封锁冲突已经明确，并在构筑兼容建议中另记；本次低支援理由仍来自该安排无法兑现，没有另界定整体角色分类与时间安排失败的关系。');
stateAmbiguous('desires_low_deck','单张壶为灵摆/指示物主计划补手的相对支援角色，和当前卡组余量分开。','九张不足以支付十张只证明当前抽牌失败；具体构筑对随机资源损失的承受范围此前也未知，不能因此把资源支援性质改成相对低类别。');
stateAmbiguous('adventurer_normal_effect_conflict','勇者整体对急袭猛禽升阶计划的相对支援角色；仪的整回合限制冲突仍作为原兼容条件保留。','通常召唤怪兽场上效果与仪的整回合限制冲突已知，但本次不把该旧失败例重新当整体低支援角色证据。');
stateAmbiguous('tenyi_effect_monster_present','大同蟠龙＋拳僧整体对超重/相剑同调的相对互补作用，和当前已有不能移走的效果怪兽分开。','已有怪兽及通常召唤耗尽只使这一次自跳/转拳僧不能开始；未独立说明该素材/处理接口在主计划中相对支援低。');
stateAmbiguous('striker_drones_occupied_main','大黄蜂＋燎里整体作为主连接计划的材料/回收接口，和当前主要怪兽区占用分开。','主区占用使本次大黄蜂不能发动，不足以决定该最低材料接口的相对支援类别。');
stateAmbiguous('predaplant_second_discard_missing','实际四件相对于捕食融合主计划的资源/融合推进作用，区分已完成的两体检索和最后立即融合函数。','第二弃手缺失只阻断最后融合，前段两体与取卡已明确完成；不能把最后一步失败传播为整个实际选择的低支援类别。');
stateAmbiguous('duster_no_backrow_now','羽毛扫对烙印融合/墓地资源主计划的相对清障支援角色，和当前对方魔陷是否存在分开。','对方没有魔陷只证明这一时点无清场贡献；未独立界定该对方单边清除函数为何在所给主计划中相对弱。');
stateAmbiguous('v5_nibiru_below_threshold','尼比鲁作为梅尔卡巴融合循环前场面处理的相对互补角色，和当前四只门槛分开。','本次对方只有四只确实不能发动，但原目的仍是先处理对方再继续融合；当前门槛失败不单独决定相对角色低。');
stateAmbiguous('v5_quick_launch_target_only_in_hand','速攻旋转＋曳光龙为龙族连接/同调主计划供调整的相对角色，和目标当前仅在手卡分开。','曳光龙不在卡组使本次速攻旋转失败，却没有改写该调整供给接口与主计划的互补关系。');
stateAmbiguous('blind-v5-kj-02','海龟④的指示物无效函数相对于星辰融合保护计划的相对支援角色；不混入其解放出场函数。','当前零坏兽指示物只证明不能支付，构筑中该无效函数的指示物供应与资源竞争接口此前未给；不能从另一海龟函数或本次失败凑成低类别。');
stateAmbiguous('blind-v6-uc-04','完整萨巴拉—唱导—阿罗汉双体路线作为邪恶双子额外恶魔资源的相对角色，和当前无合法破坏对象分开。','三件仍在，只有当前没有恶魔/里侧卡使入口失败；没有新增结构缺项或相对支援低的角色证据。');
stateAmbiguous('blind-v6-rk-04','来来—叶牡丹—绚烂整体为植物连接补身体/手牌和处理对方的相对作用，和本回合替代次数分开。','来来替代次数已用且无己方植物，只证明本次成本不能支付，不能将这条完整接口的条件性互补角色重新归低。');
stateAmbiguous('BF-ORC-05','仅限明示的对方回合骷髅复活丁吉尔苏送墓函数的角色分类；全局主策略仍未声明。','丁吉尔苏未经正规登场是该张卡的给定苏生历史，影响本次处理；三件命名结构仍齐全，不能把这一旧状态失败重新当相对支援类别，亦不补三幻魔意图。');
stateAmbiguous('BF-SPD-04','明示不占通常召唤取得双3星的用途中的贝陀螺＋竹蜻蜓整体，和当前非空场分开。','两件结构完整，非空场且无其它入口使本次不能开始，未独立说明这套保留通常召唤接口相对弱。');
stateAmbiguous('BF-SPD-06','明示双体函数中贝陀螺＋竹蜻蜓整体的相对角色，和同名检索次数分开。','同名检索本回合已用导致只能取得部分本次输出；不能用这个状态事实改变完整两件函数的相对角色类别。');
stateAmbiguous('BF-BRF-05','四件明亮融合→斜绿额外通常召唤函数的相对角色，和指定光素材当前在手卡分开。','四件结构没有缺失；尼比鲁当前位置不满足卡组素材仅阻断本次融合，不能当构筑/相对支援低类别证据。');
stateAmbiguous('BF-NIB-02','只限明示尼比鲁场面交易为之后行动留空间的用途；不从牌表补未声明主策略。','四只门槛只导致当前不能发动，原文没有另给整体弱支援的角色关系证据。');
stateAmbiguous('BF-NIB-03','只限明示尼比鲁场面交易的相对作用，和当前战斗阶段分开。','时点在战斗阶段导致本次不能发动，不等于指定单张场面处理函数相对支援低；全局主策略也仍未声明。');
stateAmbiguous('BF-NIB-05','只限明示尼比鲁单张场面处理用途的相对作用，和该卡当前在墓地分开。','单张仍在查询中，墓地位置而非结构排除使本次不能用手卡效果；不凭这个旧位置反例重新生成低类别。');
stateAmbiguous('BF-NIB-06','只限尼比鲁明示场面交易的相对角色；自奏效果后仍适用的暗属性限制继续作为原机械兼容事实单列。','持续暗属性自肃与光属性尼比鲁冲突已在构筑兼容建议中否定这次安排，但本条未声明独立主策略；本轮不把此前基于当前安排失败保留未知的支援类别翻案。');

assert.equal(N.size,44);
const rows=low.map(r=>{const n=N.get(r.case_id);assert(n,'Missing '+r.case_id);return {case_id:r.case_id,category:n.category,confidence:n.confidence,precise_scope:n.precise_scope,evidence_quote:r.objective,reason:n.reason,original_numeric_degree_not_reasserted:true};});
const categoryCounts=rows.reduce((a,r)=>{a[r.category]=(a[r.category]||0)+1;return a;},{});
const basisCounts={};for(const r of rows){const b=N.get(r.case_id).basis;basisCounts[b]=(basisCounts[b]||0)+1;}
const lowPrimary=rows.filter(r=>r.category==='supported_low'&&pmap.get(r.case_id).primary_plan_text!==null).length;
const lowLocal=rows.filter(r=>r.category==='supported_low'&&pmap.get(r.case_id).primary_plan_text===null).length;
for(const p of sourceHashes)assert.equal(sha(path.join(root,p.file.slice(3))),p.sha256);
for(const p of protectedHashes)assert.equal(sha(path.join(out,p.file)),p.sha256);
assert.equal(new Set(rows.map(r=>r.case_id)).size,44);
const report={schema_version:'support-low-scope-resolution-v1',scope:'仅旧Support非null且<0.5的44条既有记录；区分类别证据与原精确数值，不新增情境/家族/终验，不改旧标签。',authorship:'模型代理；已见旧标签/旧rationale，持续隔离预测、模型表现及训练；不是独立盲终验或人工金标。',category_definitions:{supported_low:'原实际选择整体在给定明确主计划或明示用途中的相对支援匹配低有类别证据；不声称所有可能用途无用，不重申原数值程度。',still_ambiguous:'现有资料不能支持该相对低类别；先前瞬时/给定状态失败的未知保持，不把执行失败翻作新负例。'},summary:{reviewed_cases:44,category_counts:categoryCounts,supported_low_with_explicit_primary_plan:lowPrimary,supported_low_with_declared_local_use_only:lowLocal,basis_counts:basisCounts,precise_numeric_degrees_reasserted:0},cases:rows,provenance:{selection_rule:'reference_audit_intake.json中roles[3]非null且<0.5；仅用该规则限定本轮范围，没有读预测。',input_files:sourceHashes,protected_existing_deliverables:protectedHashes,primary_plans_frozen_sha256:freeze.primary_plans_sha256,original_labels_modified:false,core_support_overlap_positive_examples_modified:false,new_numeric_role_degrees_created:false,predictions_metrics_models_weights_training_sources_or_sessions_read:false,training_executed:false},remaining_gaps:'still_ambiguous条目保留逐条范围：只有本次条件失败、整体/子函数关系仍不足、或未声明相对角色主计划；没有要求排除所有潜在未来用途，也没有新增实战/引擎实验门槛。'};
fs.writeFileSync(path.join(out,'support_low_scope_resolution.json'),JSON.stringify(report,null,2)+'\n','utf8');
console.log(JSON.stringify({reviewed:44,category_counts:categoryCounts,supported_low_with_explicit_primary_plan:lowPrimary,supported_low_with_declared_local_use_only:lowLocal,basis_counts:basisCounts,old_files_unchanged:true},null,2));
