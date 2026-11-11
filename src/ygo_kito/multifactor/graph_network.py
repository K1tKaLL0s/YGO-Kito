"""Sparse v3 graph encoder and query readout. Opaque refs are addresses only."""
import torch
from torch import nn

from .contracts import ANALYSIS_MODES, GRAPH_FUNCTIONS, GRAPH_RELATIONS, GRAPH_VERSION, TASK_DOMAINS, FactorContractError
from .task_queries import (BINARY_COORDINATES, CATEGORY_COORDINATES, LEARNED_TASKS, observation_view,
                           query_domain, training_domain, validate_query, INTENT_FACTORS)

CONTEXT_WIDTH = len(ANALYSIS_MODES)+11


def encode_graph_batch(values, *, device, config, training=False):
    if not isinstance(values,(tuple,list)) or not 1<=len(values)<=64:
        raise FactorContractError("1..64 graph observations required")
    views = [observation_view(v) for v in values]
    if any(not g.nodes for _,g,_ in views):
        raise FactorContractError('v3 graphs require explicit section/unknown nodes, not an empty tensor graph')
    total_nodes = sum(len(g.nodes) for _,g,_ in views)
    total_edges = sum(len(g.edges) for _,g,_ in views)
    if total_nodes>config.graph_node_budget or total_edges>config.graph_edge_budget:
        raise FactorContractError("graph tensor budget exceeded; no truncated batch")
    numeric,edges,owners,structural,contexts,indices,domains,intents = [],[],[],[],[],[],[],[]
    for b,(example,graph,candidates) in enumerate(views):
        offset = len(numeric)
        index = {n.ref:offset+i for i,n in enumerate(graph.nodes)}
        indices.append(index)
        domain = query_domain(example,graph,candidates)
        if training and isinstance(values[b],dict):
            domain = training_domain(domain,candidates,values[b].get('supervision',{}).get('training_queries',()))
        domains.append(domain)
        for node in graph.nodes:
            numeric.append(node.numeric_values())
            owners.append(b)
            structural.append(node.kind!="resource" and dict(node.attributes).get("scope_state")!=1)
        for edge in graph.edges:
            edges.append((index[edge.source],index[edge.target],GRAPH_RELATIONS.index(edge.kind),edge.quantity,edge.confidence))
        deck = example.insertion.apply(example.deck) if example.insertion else example.deck
        counts = [None if deck is None or getattr(deck,s) is None else sum(n for _,n in getattr(deck,s)) for s in ("main","extra","side")]
        contexts.append([float(example.analysis_mode==m) for m in ANALYSIS_MODES]+
            [float(n is not None) for n in counts]+[float(n==0) for n in counts]+
            [0.0 if n is None else float(n) for n in counts]+
            [float(example.visible_state is not None),float(example.analysis_context.public_resources is not None)])
        intents.append([channel for name in INTENT_FACTORS for channel in example.context.get(name).channels()])
    features = torch.tensor(numeric,dtype=torch.float32,device=device)
    # Signed log retains zero/unknown masks and quantities without large ATK/LP
    # dominating the first layer. The transform is in the feature binding.
    features = features.sign()*features.abs().log1p()
    if edges:
        edge_index = torch.tensor([[e[0],e[1]] for e in edges],dtype=torch.long,device=device).t().contiguous()
        relation = torch.zeros(len(edges),len(GRAPH_RELATIONS)+2,device=device)
        for i,(_,_,kind,quantity,confidence) in enumerate(edges):
            relation[i,kind] = 1
            relation[i,-2] = float(quantity)
            relation[i,-1] = confidence
        relation[:,-2] = relation[:,-2].log1p()
    else:
        edge_index = torch.empty(2,0,dtype=torch.long,device=device)
        relation = torch.empty(0,len(GRAPH_RELATIONS)+2,device=device)
    context = torch.tensor(contexts,dtype=torch.float32,device=device)
    context[:,len(ANALYSIS_MODES)+6:len(ANALYSIS_MODES)+9] = context[:,len(ANALYSIS_MODES)+6:len(ANALYSIS_MODES)+9].log1p()
    return dict(schema_version=GRAPH_VERSION,nodes=features,edge_index=edge_index,edge_features=relation,
        intent=torch.tensor(intents,dtype=torch.float32,device=device),
        graph_index=torch.tensor(owners,dtype=torch.long,device=device),
        structural_mask=torch.tensor(structural,dtype=torch.bool,device=device),context=context,
        indices=tuple(indices),domains=tuple(domains),examples=tuple(v[0] for v in views),graph_count=len(views))


class GraphRoleNetwork(nn.Module):
    def __init__(self,config):
        super().__init__()
        from .contracts import Factors,GraphNode
        width = config.hidden_dim
        self.config = config
        node_width = len(GraphNode("shape","card",Factors("group")).numeric_values())
        devices = list(range(torch.cuda.device_count())) if torch.cuda.is_initialized() else []
        with torch.random.fork_rng(devices=devices):
            torch.manual_seed(config.seed)
            self.node_encoder = nn.Sequential(nn.Linear(node_width,width),nn.SiLU())
            self.context_encoder = nn.Sequential(nn.Linear(CONTEXT_WIDTH,width),nn.SiLU())
            self.intent_encoder = nn.Sequential(nn.Linear(4*len(INTENT_FACTORS),width),nn.SiLU())
            self.relation_encoder = nn.Sequential(nn.Linear(len(GRAPH_RELATIONS)+2,width),nn.SiLU())
            self.messages = nn.ModuleList(nn.Sequential(nn.Linear(3*width,width),nn.SiLU()) for _ in range(config.message_rounds))
            self.updates = nn.ModuleList(nn.Sequential(nn.Linear(4*width,width),nn.SiLU(),nn.LayerNorm(width)) for _ in range(config.message_rounds))
            self.route_projection = nn.Linear(width,width,bias=False) if config.use_route_features else None
            self.function_encoder = nn.Linear(len(GRAPH_FUNCTIONS),width,bias=False)
            self.query_readout = nn.Sequential(nn.Linear(5*width,width),nn.SiLU(),nn.Dropout(config.dropout))
            self.heads = nn.ModuleDict({task:nn.Linear(width,
                len(BINARY_COORDINATES[task]) if task in BINARY_COORDINATES else len(TASK_DOMAINS[task]) if task in CATEGORY_COORDINATES else 1)
                for task in LEARNED_TASKS})

    def _stream(self,batch,mask,context):
        node = self.node_encoder(batch["nodes"])*mask[:,None]
        relation = self.relation_encoder(batch["edge_features"])
        source,target = batch["edge_index"]
        enabled = mask[source]&mask[target]
        for message,update in zip(self.messages,self.updates):
            incoming,outgoing = torch.zeros_like(node),torch.zeros_like(node)
            indegree,outdegree = node.new_zeros(len(node),1),node.new_zeros(len(node),1)
            for start in range(0,len(source),self.config.graph_block_size):
                s,t = source[start:start+self.config.graph_block_size],target[start:start+self.config.graph_block_size]
                active = enabled[start:start+self.config.graph_block_size,None].to(node.dtype)
                values = message(torch.cat((node[s],node[t],relation[start:start+self.config.graph_block_size]),-1))*active
                incoming.index_add_(0,t,values)
                outgoing.index_add_(0,s,values)
                indegree.index_add_(0,t,active)
                outdegree.index_add_(0,s,active)
            incoming = incoming/indegree.clamp_min(1)
            outgoing = outgoing/outdegree.clamp_min(1)
            if self.route_projection is not None:
                # An optional observed two-hop cue, never a successful CB trace.
                route = torch.zeros_like(node)
                route.index_add_(0,target,outgoing[source]*enabled[:,None])
                incoming = incoming+self.route_projection(route/indegree.clamp_min(1))
            pieces = []
            for start in range(0,len(node),self.config.graph_block_size):
                end = start+self.config.graph_block_size
                ctx = context[batch["graph_index"][start:end]]
                pieces.append(update(torch.cat((node[start:end],incoming[start:end],outgoing[start:end],ctx),-1)))
            node = torch.cat(pieces,0)*mask[:,None]
        pooled = node.new_zeros(batch["graph_count"],node.shape[-1])
        counts = node.new_zeros(batch["graph_count"],1)
        pooled.index_add_(0,batch["graph_index"],node)
        counts.index_add_(0,batch["graph_index"],mask[:,None].to(node.dtype))
        return node,pooled/counts.clamp_min(1)

    def forward(self,batch):
        if batch.get("schema_version")!=GRAPH_VERSION:
            raise FactorContractError("v3 network requires v3 graph tensors")
        context = self.context_encoder(batch["context"])
        full,global_full = self._stream(batch,torch.ones(len(batch["nodes"]),dtype=torch.bool,device=context.device),context)
        if self.config.stream_mode=="dual":
            structural_context = batch["context"].clone()
            structural_context[:,-2:] = 0
            structural,global_structural = self._stream(batch,batch["structural_mask"],self.context_encoder(structural_context))
        else:
            structural,global_structural = full,global_full
        return dict(node=full,structural_node=structural,global_node=global_full,global_structural=global_structural,
                    intent=self.intent_encoder(batch["intent"]))

    def score_queries(self,output,batch,queries):
        """queries index a fixed fact domain; no label value is an argument."""
        rows,tasks,coordinates = [],[],[]
        for b,task,subject,coordinate in queries:
            if type(b) is not int or not 0<=b<batch['graph_count']:
                raise FactorContractError('query graph index outside batch')
            subject = validate_query(batch["domains"][b],task,subject,coordinate)
            if task=="transferability" and len(subject)==1:
                subject = subject+("function:"+batch["domains"][b]["nodes"][subject[0]].functions[0],)
            structural = task in ("mechanism","axis_membership","axis_function","axis_origin","transferability","legacy:large_axis","legacy:small_axis")
            node = output["structural_node"] if structural else output["node"]
            pooled = output["global_structural"] if structural else output["global_node"]
            zero = node.new_zeros(node.shape[-1])
            parts = []
            for position,ref in enumerate(subject):
                virtual = batch['domains'][b]['virtual'].get(ref)
                if task in ('function_role','contribution','transferability') and position==len(subject)-1 and len(subject)>1:
                    function = node.new_zeros(len(GRAPH_FUNCTIONS))
                    function[GRAPH_FUNCTIONS.index(ref[9:])] = 1
                    parts.append(self.function_encoder(function))
                elif virtual is not None:
                    members = sum(node[batch['indices'][b][r]]*n for r,n in virtual['members'])/sum(n for _,n in virtual['members'])
                    parts.append((members+node[batch['indices'][b][virtual['source']]])/2)
                elif ref in batch["indices"][b]:
                    parts.append(node[batch["indices"][b][ref]])
                else:
                    raise FactorContractError('query endpoint is not an observed node or controlled function')
            parts += [zero]*(3-len(parts))
            contextual_pool=pooled[b] if structural else pooled[b]+output["intent"][b]
            rows.append(torch.cat((*parts,contextual_pool,parts[0]-parts[1]),-1))
            tasks.append(task)
            coordinates.append(coordinate)
        if not rows:
            return []
        hidden = self.query_readout(torch.stack(rows))
        result = []
        for i,(task,coordinate) in enumerate(zip(tasks,coordinates)):
            logits = self.heads[task](hidden[i])
            result.append(logits[BINARY_COORDINATES[task].index(coordinate)] if task in BINARY_COORDINATES else logits if task in CATEGORY_COORDINATES else logits[0])
        return result

    def score_preference(self,output,batch,left_key,right_key,*,left_index=0,right_index=1):
        left = output["node"][batch["indices"][left_index][left_key]]
        right = output["node"][batch["indices"][right_index][right_key]]
        global_context = (output["global_node"][left_index]+output["global_node"][right_index]+
                          output["intent"][left_index]+output["intent"][right_index])/2
        shared = self.query_readout(torch.cat((left,right,torch.zeros_like(left),global_context,left-right)))
        return self.heads["copy_preference"](shared)
