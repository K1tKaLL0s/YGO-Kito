// Own audit harness. Compilation/execution is separate from Python preparation.
// Metadata-only still loads a third-party assembly. --construct additionally
// initializes its SQLite catalog and constructs every registered Executor.
// It never calls GameClient.Start/RunAndroid/Test1 and never opens a game room.
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Runtime.Serialization;
using System.Runtime.Serialization.Json;
using System.Security.Cryptography;

[DataContract] public class Resource {
    [DataMember(IsRequired=true)] public string path;
    [DataMember(IsRequired=true)] public string sha256;
}
[DataContract] public class ExpectedBot {
    [DataMember(IsRequired=true)] public string full_type;
    [DataMember(IsRequired=true)] public string deck_name;
    [DataMember(IsRequired=true)] public string deck_file;
    [DataMember(IsRequired=true)] public string level;
    [DataMember(IsRequired=true)] public Resource selected_deck;
}
[DataContract] public class AuditInput {
    [DataMember(IsRequired=true)] public int schema_version;
    [DataMember(IsRequired=true)] public string source_id;
    [DataMember(IsRequired=true)] public string assembly_path;
    [DataMember(IsRequired=true)] public string assembly_sha256;
    [DataMember(IsRequired=true)] public string source_root;
    [DataMember(IsRequired=true)] public Resource cards;
    [DataMember(IsRequired=true)] public Resource[] resources;
    [DataMember(IsRequired=true)] public ExpectedBot[] bots;
}
[DataContract] public class BotResult {
    [DataMember] public string full_type;
    [DataMember] public string deck_name;
    [DataMember] public bool metadata_matched;
    [DataMember] public bool resource_verified;
    [DataMember] public bool constructed;
    [DataMember] public string error;
}
[DataContract] public class AuditResult {
    [DataMember] public int schema_version=1;
    [DataMember] public bool assembly_loaded;
    [DataMember] public bool constructor_execution_requested;
    [DataMember] public bool all_expected_executors_matched;
    [DataMember] public bool all_resources_verified;
    [DataMember] public bool normal_duel_verified=false;
    [DataMember] public bool strength_verified=false;
    [DataMember] public bool history_verified=false;
    [DataMember] public bool training_connected=false;
    [DataMember] public string assembly_sha256;
    [DataMember] public string error;
    [DataMember] public List<BotResult> bots=new List<BotResult>();
}
public static class BotAssemblyAudit {
    static string Hash(string path) {
        using(var sha=SHA256.Create()) using(var f=File.OpenRead(path))
            return BitConverter.ToString(sha.ComputeHash(f)).Replace("-", "").ToLowerInvariant();
    }
    static void Check(Resource resource) {
        if(resource==null || !File.Exists(resource.path) || Hash(resource.path)!=resource.sha256)
            throw new InvalidDataException("Explicit resource absent or checksum differs");
    }
    static object Invoke(Type type, string method, params object[] args) {
        return type.GetMethod(method, BindingFlags.Public|BindingFlags.Static).Invoke(null,args);
    }
    static string Error(Exception error) {
        while(error is TargetInvocationException && error.InnerException!=null) error=error.InnerException;
        return error.GetType().Name+": "+error.Message;
    }
    public static int Main(string[] args) {
        if(args.Length<2 || args.Length>3 || (args.Length==3 && args[2]!="--construct")) return 2;
        var result=new AuditResult();
        result.constructor_execution_requested=args.Length==3;
        try {
            AuditInput spec;
            using(var f=File.OpenRead(args[0])) spec=(AuditInput)new DataContractJsonSerializer(typeof(AuditInput)).ReadObject(f);
            int count=spec.source_id=="ice"?73:spec.source_id=="pure"?74:0;
            if(spec.schema_version!=1 || count==0 || spec.bots.Length!=count ||
               spec.bots.Select(x=>x.full_type).Distinct().Count()!=count ||
               spec.bots.Select(x=>x.deck_name).Distinct().Count()!=count)
                throw new InvalidDataException("Expected full fixed Executor set is missing or repeated");
            foreach(var expected in spec.bots)
                result.bots.Add(new BotResult {full_type=expected.full_type,deck_name=expected.deck_name});
            if(Hash(spec.assembly_path)!=spec.assembly_sha256) throw new InvalidDataException("Assembly checksum differs");
            foreach(var resource in spec.resources) Check(resource);
            Directory.SetCurrentDirectory(spec.source_root);
            var assembly=Assembly.LoadFrom(spec.assembly_path);
            result.assembly_loaded=true; result.assembly_sha256=Hash(spec.assembly_path);
            var actual=new Dictionary<string,CustomAttributeData>();
            foreach(var type in assembly.GetTypes()) {
                var attributes=CustomAttributeData.GetCustomAttributes(type)
                    .Where(a=>a.AttributeType.FullName=="WindBot.Game.AI.DeckAttribute").ToArray();
                if(attributes.Length>1) throw new InvalidDataException("Repeated Deck registration");
                if(attributes.Length==1) actual.Add(type.FullName,attributes[0]);
            }
            if(actual.Count!=count || !actual.Keys.OrderBy(x=>x).SequenceEqual(spec.bots.Select(x=>x.full_type).OrderBy(x=>x)))
                throw new InvalidDataException("Compiled Executor types differ: reduced/unexpected assembly");
            bool catalog=false;
            if(result.constructor_execution_requested) {
                // Match the pinned Program initialization of its configuration
                // caches. No file or network option is supplied.
                Invoke(assembly.GetType("WindBot.Config",true),"Load",new object[]{new string[0]});
                Check(spec.cards);
                Invoke(assembly.GetType("YGOSharp.OCGWrapper.NamedCardsManager",true),"Init",spec.cards.path);
                assembly.GetType("WindBot.Program",true).GetField("Rand",BindingFlags.NonPublic|BindingFlags.Static)
                    .SetValue(null,new Random(7));
                Invoke(assembly.GetType("WindBot.Game.AI.DecksManager",true),"Init");
                catalog=true;
            }
            for(int ordinal=0;ordinal<spec.bots.Length;ordinal++) {
                var expected=spec.bots[ordinal]; var row=result.bots[ordinal];
                try {
                    var values=actual[expected.full_type].ConstructorArguments;
                    if(values.Count!=3 || (string)values[0].Value!=expected.deck_name ||
                       (string)values[1].Value!=expected.deck_file || (string)values[2].Value!=expected.level)
                        throw new InvalidDataException("Exact Deck attribute differs");
                    row.metadata_matched=true;
                    if(!catalog) continue;
                    Check(expected.selected_deck);
                    foreach(var raw in File.ReadAllLines(expected.selected_deck.path)) {
                        string line=raw.Trim(); if(line.Length==0 || line[0]=='#' || line=="!side") continue;
                        int id; if(!Int32.TryParse(line,out id) || id<=0 ||
                           Invoke(assembly.GetType("YGOSharp.OCGWrapper.NamedCard",true),"Get",id)==null)
                            throw new InvalidDataException("Selected YDK has unknown/invalid catalog card");
                    }
                    row.resource_verified=true;
                    var info=Activator.CreateInstance(assembly.GetType("WindBot.WindBotInfo",true));
                    info.GetType().GetProperty("Deck").SetValue(info,expected.deck_name,null);
                    info.GetType().GetProperty("Chat").SetValue(info,false,null);
                    // Exact pinned APIs differ: Pure adds an optional preset
                    // connection parameter. Reflection does not omit it.
                    object[] gameArgs=spec.source_id=="pure"?new object[]{info,null}:new object[]{info};
                    var game=Activator.CreateInstance(assembly.GetType("WindBot.Game.GameClient",true),gameArgs);
                    var duel=Activator.CreateInstance(assembly.GetType("WindBot.Game.Duel",true));
                    var ai=Activator.CreateInstance(assembly.GetType("WindBot.Game.GameAI",true),new object[]{game,duel});
                    var manager=assembly.GetType("WindBot.Game.AI.DecksManager",true);
                    if(!(bool)Invoke(manager,"HasDeck",expected.deck_name)) throw new InvalidDataException("Deck not registered");
                    var executor=Invoke(manager,"Instantiate",ai,duel);
                    if(executor==null || executor.GetType().FullName!=expected.full_type)
                        throw new InvalidDataException("Constructor/factory selected a different Executor");
                    row.constructed=true;
                } catch(Exception error) { row.error=Error(error); }
            }
            result.all_expected_executors_matched=result.bots.Count==count && result.bots.All(r=>r.metadata_matched &&
                (!result.constructor_execution_requested || (r.resource_verified && r.constructed)));
            foreach(var resource in spec.resources) Check(resource);
            if(result.constructor_execution_requested) Check(spec.cards);
            result.all_resources_verified=!result.constructor_execution_requested || result.bots.All(r=>r.resource_verified);
        } catch(Exception error) {
            result.error=Error(error);
            foreach(var row in result.bots) if(row.error==null && !row.constructed)
                row.error="not_completed_after_global_failure: "+result.error;
        }
        using(var output=new FileStream(args[1],FileMode.CreateNew,FileAccess.Write))
            new DataContractJsonSerializer(typeof(AuditResult)).WriteObject(output,result);
        return result.error==null && result.all_expected_executors_matched?0:2;
    }
}
