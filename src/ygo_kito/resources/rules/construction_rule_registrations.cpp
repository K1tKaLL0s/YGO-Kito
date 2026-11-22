// Read the locked core's card and field registrations after initial_effect.
#include <algorithm>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <iterator>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include "card.h"
#include "duel.h"
#include "effect.h"
#include "field.h"
#include "group.h"
#include "interpreter.h"
#include "lauxlib.h"
#include "lua.h"
#include "ocgapi.h"
#include "construction_rule_effect.h"

namespace fs = std::filesystem;

static std::unordered_map<uint32_t, card_data> rows;
static fs::path script_root;
static std::unordered_map<std::string, std::vector<byte>> script_bytes;
static std::vector<std::string> diagnostics;

static byte* locked_script(const char* name, int* length) {
    std::string relative(name);
    if (relative.rfind("./script/", 0) == 0)
        relative.erase(0, 9);
    else if (relative.rfind("script/", 0) == 0)
        relative.erase(0, 7);
    *length = 0;
    auto known = script_bytes.find(relative);
    if (known == script_bytes.end()) {
        std::error_code error;
        auto file = fs::weakly_canonical(script_root / relative, error);
        auto inside = file.lexically_relative(script_root);
        if (error || inside.empty() || *inside.begin() == ".." || file.extension() != ".lua")
            return nullptr;
        std::ifstream stream(file, std::ios::binary);
        auto& content = script_bytes[relative];
        content.assign(std::istreambuf_iterator<char>(stream), {});
        known = script_bytes.find(relative);
    }
    *length = static_cast<int>(known->second.size());
    return known->second.empty() ? nullptr : known->second.data();
}

static uint32_t locked_card(uint32_t code, card_data* data) {
    auto found = rows.find(code);
    if (found != rows.end())
        *data = found->second;
    else {
        data->clear();
        diagnostics.push_back("missing card data: " + std::to_string(code));
    }
    return 0;
}

static uint32_t note_diagnostic(intptr_t handle, uint32_t) {
    const auto& buffer = reinterpret_cast<const duel*>(handle)->strbuffer;
    std::string message(std::begin(buffer), std::find(std::begin(buffer), std::end(buffer), '\0'));
    for (auto& character : message)
        if (character == '\t' || character == '\r' || character == '\n')
            character = ' ';
    diagnostics.push_back(message);
    return 0;
}

static std::vector<effect*> registrations(duel* engine, uint32_t code, card*& printed) {
    const auto& field = engine->game_field->effects.indexer;
    std::unordered_set<effect*> earlier;
    for (const auto& entry : field)
        earlier.insert(entry.first);
    printed = engine->new_card(code);
    std::vector<effect*> effects(printed->initial_effect.begin(), printed->initial_effect.end());
    for (const auto& entry : field)
        if (earlier.find(entry.first) == earlier.end() &&
                printed->initial_effect.find(entry.first) == printed->initial_effect.end())
            effects.push_back(entry.first);
    std::sort(effects.begin(), effects.end(), [](effect* a, effect* b) { return a->ref_handle < b->ref_handle; });
    return effects;
}

static void stock_entry(lua_State* lua, card* item, int index, int copy, int location) {
    item->current.controler = item->owner = 0;
    item->current.location = location;
    item->current.position = location == LOCATION_EXTRA || location == LOCATION_DECK ? POS_FACEDOWN_DEFENSE : POS_FACEUP_ATTACK;
    lua_createtable(lua, 3, 0);
    lua_rawgeti(lua, LUA_REGISTRYINDEX, item->ref_handle);
    lua_rawseti(lua, -2, 1);
    lua_pushinteger(lua, copy);
    lua_rawseti(lua, -2, 2);
    lua_pushinteger(lua, location);
    lua_rawseti(lua, -2, 3);
    lua_rawseti(lua, -2, index);
}

static void stock_budget(lua_State* lua, lua_Debug*) {
    luaL_error(lua, "construction fusion stock instruction budget reached");
}

static void write_stock_options(lua_State* lua) {
    std::cout << "stock\t" << lua_tostring(lua, -2);
    lua_pushnil(lua);
    while (lua_next(lua, -2)) {
        std::cout << '\t' << lua_tointeger(lua, -2);
        for (int i = 1; i <= lua_rawlen(lua, -1); ++i) {
            lua_rawgeti(lua, -1, i);
            lua_rawgeti(lua, -1, 1);
            const auto copy = lua_tointeger(lua, -1);
            lua_pop(lua, 1);
            lua_rawgeti(lua, -1, 2);
            std::cout << ',' << copy << ':' << lua_tointeger(lua, -1);
            lua_pop(lua, 2);
        }
        lua_pop(lua, 1);
    }
    std::cout << '\n';
}

static void fusion_stock(intptr_t handle, const char* shim, const std::vector<uint32_t>& stock,
                         int main_count, int source, size_t ordinal, int location, bool alternate) {
    auto* engine = reinterpret_cast<duel*>(handle);
    auto* lua = engine->lua->lua_state;
    card* handler = nullptr;
    const auto effects = registrations(engine, stock.at(source - 1), handler);
    if (ordinal >= effects.size() || !effects[ordinal]->target || !effects[ordinal]->operation ||
            luaL_loadfile(lua, shim) != LUA_OK || lua_pcall(lua, 0, 1, 0) != LUA_OK) {
        std::cout << "stock\tunknown\n";
        return;
    }
    lua_rawgeti(lua, LUA_REGISTRYINDEX, effects[ordinal]->target);
    lua_rawgeti(lua, LUA_REGISTRYINDEX, effects[ordinal]->ref_handle);
    lua_newtable(lua);
    int entry = 0;
    for (int i = 1; i <= static_cast<int>(stock.size()); ++i) {
        if (i == source) {
            stock_entry(lua, handler, ++entry, i, location);
        } else if (i <= main_count) {
            for (const int zone : {LOCATION_HAND, LOCATION_GRAVE, LOCATION_MZONE, LOCATION_DECK, LOCATION_REMOVED})
                stock_entry(lua, engine->new_card(stock[i - 1]), ++entry, i, zone);
        } else {
            stock_entry(lua, engine->new_card(stock[i - 1]), ++entry, i, LOCATION_EXTRA);
        }
    }
    lua_newtable(lua);
    for (int i = main_count + 1; i <= static_cast<int>(stock.size()); ++i) {
        lua_pushboolean(lua, true);
        lua_rawseti(lua, -2, i);
    }
    lua_pushboolean(lua, alternate);
    lua_sethook(lua, stock_budget, LUA_MASKCOUNT, 1500000);
    const auto result = lua_pcall(lua, 5, 2, 0);
    lua_sethook(lua, nullptr, 0, 0);
    if (result != LUA_OK || !diagnostics.empty()) {
        std::cout << "stock\tunknown\n";
        if (result != LUA_OK && lua_isstring(lua, -1))
            std::cerr << lua_tostring(lua, -1) << '\n';
        for (const auto& message : diagnostics)
            std::cerr << message << '\n';
        return;
    }
    write_stock_options(lua);
}

static int l_probe_place(lua_State* L) {
    card* pcard = lua_touserdata(L, 1) ? *(card**)lua_touserdata(L, 1) : nullptr;
    if (!pcard)
        return 0;
    uint8_t owner = static_cast<uint8_t>(luaL_optinteger(L, 2, 0));
    uint8_t player = static_cast<uint8_t>(luaL_optinteger(L, 3, 0));
    uint8_t location = static_cast<uint8_t>(luaL_optinteger(L, 4, LOCATION_MZONE));
    uint8_t seq = static_cast<uint8_t>(luaL_optinteger(L, 5, 0));
    uint32_t pos = static_cast<uint32_t>(luaL_optinteger(L, 6, POS_FACEUP_ATTACK));
    uint8_t pzone = static_cast<uint8_t>(lua_toboolean(L, 7));
    bool proc_ok = lua_gettop(L) >= 8 ? lua_toboolean(L, 8) : (location == LOCATION_MZONE);
    duel* pd = pcard->pduel;
    if (pcard->current.location != 0) {
        pcard->enable_field_effect(false);
        pd->game_field->remove_card(pcard);
    }
    pcard->owner = owner;
    pcard->sendto_param.position = pos;
    pcard->current.position = pos;
    pcard->set_status(STATUS_PROC_COMPLETE, proc_ok ? TRUE : FALSE);
    pd->game_field->add_card(player, pcard, location, seq, pzone);
    if (pcard->current.location == 0) {
        pcard->current.position = 0;
        pcard->set_status(STATUS_EFFECT_ENABLED | STATUS_PROC_COMPLETE, FALSE);
        lua_pushboolean(L, 0);
        return 1;
    }
    const uint8_t actual_loc = pcard->current.location;
    const uint32_t actual_pos = (actual_loc == location) ? pos : pcard->sendto_param.position;
    pcard->current.position = actual_pos;
    pcard->set_status(STATUS_EFFECT_ENABLED, ((actual_loc & LOCATION_ONFIELD) && (actual_pos & POS_FACEUP)) ? TRUE : FALSE);
    if (!(actual_loc & LOCATION_ONFIELD) || (actual_pos & POS_FACEUP))
        pcard->enable_field_effect(true);
    pd->game_field->adjust_instant();
    lua_pushboolean(L, actual_loc == location && pcard->current.controler == player);
    return 1;
}

static int l_probe_remove(lua_State* L) {
    card* pcard = lua_touserdata(L, 1) ? *(card**)lua_touserdata(L, 1) : nullptr;
    if (!pcard)
        return 0;
    duel* pd = pcard->pduel;
    if (pcard->current.location != 0) {
        pcard->enable_field_effect(false);
        pd->game_field->remove_card(pcard);
    }
    pcard->set_status(STATUS_EFFECT_ENABLED | STATUS_PROC_COMPLETE, FALSE);
    pcard->current.position = 0;
    pcard->current.pzone = false;
    pcard->previous.location = 0;
    pd->game_field->adjust_instant();
    return 0;
}

static int l_probe_pzone_seq(lua_State* L) {
    duel* pd = interpreter::get_duel_info(L);
    uint8_t pseq = static_cast<uint8_t>(luaL_optinteger(L, 1, 0));
    lua_pushinteger(L, pd->game_field->get_pzone_sequence(pseq));
    return 1;
}

static int l_probe_set_phase(lua_State* L) {
    duel* pd = interpreter::get_duel_info(L);
    pd->game_field->infos.turn_id = static_cast<uint16_t>(luaL_optinteger(L, 1, 1));
    pd->game_field->infos.turn_player = static_cast<uint8_t>(luaL_optinteger(L, 2, 0));
    pd->game_field->infos.phase = static_cast<uint16_t>(luaL_optinteger(L, 3, PHASE_MAIN1));
    return 0;
}

static int l_probe_new_dummy(lua_State* L) {
    duel* pd = interpreter::get_duel_info(L);
    uint32_t code = static_cast<uint32_t>(luaL_optinteger(L, 1, TEMP_CARD_ID));
    card* pcard = pd->new_card(code);
    if (code == TEMP_CARD_ID) {
        pcard->data.type = TYPE_MONSTER | TYPE_NORMAL;
        pcard->data.level = 4;
        pcard->data.attribute = ATTRIBUTE_EARTH;
        pcard->data.race = RACE_WARRIOR;
        pcard->data.attack = 1000;
        pcard->data.defense = 1000;
    }
    lua_rawgeti(L, LUA_REGISTRYINDEX, pcard->ref_handle);
    return 1;
}

static void push_effect_table(lua_State* lua, effect* pe, size_t ordinal, bool on_card) {
    lua_newtable(lua);
    lua_pushinteger(lua, static_cast<lua_Integer>(ordinal));
    lua_setfield(lua, -2, "ordinal");
    lua_pushstring(lua, on_card ? "card" : "field");
    lua_setfield(lua, -2, "scope");
    lua_rawgeti(lua, LUA_REGISTRYINDEX, pe->ref_handle);
    lua_setfield(lua, -2, "effect");
    lua_pushinteger(lua, static_cast<lua_Integer>(pe->type));
    lua_setfield(lua, -2, "type");
    lua_pushinteger(lua, static_cast<lua_Integer>(pe->code));
    lua_setfield(lua, -2, "code");
    lua_pushinteger(lua, static_cast<lua_Integer>(pe->range));
    lua_setfield(lua, -2, "range");
    lua_pushinteger(lua, static_cast<lua_Integer>(pe->category));
    lua_setfield(lua, -2, "category");
    if (pe->condition) {
        lua_rawgeti(lua, LUA_REGISTRYINDEX, pe->condition);
        lua_setfield(lua, -2, "condition");
    }
    if (pe->cost) {
        lua_rawgeti(lua, LUA_REGISTRYINDEX, pe->cost);
        lua_setfield(lua, -2, "cost");
    }
    if (pe->target) {
        lua_rawgeti(lua, LUA_REGISTRYINDEX, pe->target);
        lua_setfield(lua, -2, "target");
    }
    if (pe->operation) {
        lua_rawgeti(lua, LUA_REGISTRYINDEX, pe->operation);
        lua_setfield(lua, -2, "operation");
    }
}

static int run_summon_stock(const char* shim, uint32_t* seed) {
    int duel_rule, main_count, extra_count, fusion_queries, ritual_queries;
    bool alternate;
    if (!(std::cin >> duel_rule >> main_count >> extra_count >> fusion_queries >> alternate >> ritual_queries))
        return 7;
    if (main_count < 0 || main_count > 75 || extra_count < 0 || extra_count > 30
            || fusion_queries < 0 || fusion_queries > 512 || ritual_queries < 0 || ritual_queries > 512)
        return 7;
    std::vector<uint32_t> stock(main_count + extra_count);
    for (auto& c : stock)
        if (!(std::cin >> c) || rows.find(c) == rows.end())
            return 7;
    struct FusionReq { int source; size_t ordinal; int location; };
    struct RitualReq { int source; size_t ordinal; };
    std::vector<FusionReq> freqs(fusion_queries);
    for (int i = 0; i < fusion_queries; ++i) {
        if (!(std::cin >> freqs[i].source >> freqs[i].ordinal >> freqs[i].location)
                || freqs[i].source < 1 || freqs[i].source > static_cast<int>(stock.size()))
            return 7;
    }
    std::vector<RitualReq> rreqs(ritual_queries);
    for (int i = 0; i < ritual_queries; ++i) {
        if (!(std::cin >> rreqs[i].source >> rreqs[i].ordinal)
                || rreqs[i].source < 1 || rreqs[i].source > static_cast<int>(stock.size()))
            return 7;
    }
    // 1. Run standard material fusion_stock checks in isolated duels (same engine shim semantics).
    fs::path fusion_shim = fs::path(shim).parent_path() / "construction_fusion_stock.lua";
    for (int i = 0; i < fusion_queries; ++i) {
        diagnostics.clear();
        const auto handle = create_duel_v2(seed);
        if (!handle)
            return 5;
        fusion_stock(handle, fusion_shim.c_str(), stock, main_count, freqs[i].source, freqs[i].ordinal, freqs[i].location, alternate);
        end_duel(handle);
    }
    // 2. Run comprehensive summon stock probe inside one MR duel.
    diagnostics.clear();
    const auto handle = create_duel_v2(seed);
    if (!handle)
        return 5;
    set_player_info(handle, 0, 8000, 0, 0);
    set_player_info(handle, 1, 8000, 0, 0);
    start_duel(handle, static_cast<uint32_t>(duel_rule) << 16);
    auto* engine = reinterpret_cast<duel*>(handle);
    engine->game_field->infos.turn_id = 1;
    engine->game_field->infos.turn_player = 0;
    engine->game_field->infos.phase = PHASE_MAIN1;
    auto* lua = engine->lua->lua_state;
    if (luaL_loadfile(lua, shim) != LUA_OK || lua_pcall(lua, 0, 1, 0) != LUA_OK) {
        if (lua_isstring(lua, -1))
            std::cerr << lua_tostring(lua, -1) << '\n';
        end_duel(handle);
        return 6;
    }
    lua_newtable(lua); // helpers
    lua_pushcfunction(lua, l_probe_place); lua_setfield(lua, -2, "place");
    lua_pushcfunction(lua, l_probe_remove); lua_setfield(lua, -2, "remove");
    lua_pushcfunction(lua, l_probe_pzone_seq); lua_setfield(lua, -2, "pzone_seq");
    lua_pushcfunction(lua, l_probe_set_phase); lua_setfield(lua, -2, "set_phase");
    lua_pushcfunction(lua, l_probe_new_dummy); lua_setfield(lua, -2, "new_dummy");

    lua_newtable(lua); // stock_entries
    for (int i = 1; i <= static_cast<int>(stock.size()); ++i) {
        card* pcard = nullptr;
        const auto effects = registrations(engine, stock[i - 1], pcard);
        lua_newtable(lua);
        lua_pushinteger(lua, i); lua_setfield(lua, -2, "copy");
        lua_pushinteger(lua, stock[i - 1]); lua_setfield(lua, -2, "code");
        lua_pushstring(lua, i <= main_count ? "main" : "extra"); lua_setfield(lua, -2, "section");
        lua_rawgeti(lua, LUA_REGISTRYINDEX, pcard->ref_handle); lua_setfield(lua, -2, "card");
        lua_newtable(lua);
        for (size_t ei = 0; ei < effects.size(); ++ei) {
            const bool on_card = pcard->initial_effect.find(effects[ei]) != pcard->initial_effect.end();
            push_effect_table(lua, effects[ei], ei, on_card);
            lua_rawseti(lua, -2, static_cast<lua_Integer>(ei + 1));
        }
        lua_setfield(lua, -2, "effects");
        lua_rawseti(lua, -2, i);
    }

    lua_newtable(lua); // fusion_reqs
    for (size_t i = 0; i < freqs.size(); ++i) {
        lua_newtable(lua);
        lua_pushinteger(lua, static_cast<lua_Integer>(i)); lua_setfield(lua, -2, "qi");
        lua_pushinteger(lua, freqs[i].source); lua_setfield(lua, -2, "copy");
        lua_pushinteger(lua, static_cast<lua_Integer>(freqs[i].ordinal)); lua_setfield(lua, -2, "ordinal");
        lua_pushinteger(lua, freqs[i].location); lua_setfield(lua, -2, "location");
        lua_rawseti(lua, -2, static_cast<lua_Integer>(i + 1));
    }

    lua_newtable(lua); // ritual_reqs
    for (size_t i = 0; i < rreqs.size(); ++i) {
        lua_newtable(lua);
        lua_pushinteger(lua, static_cast<lua_Integer>(i)); lua_setfield(lua, -2, "qi");
        lua_pushinteger(lua, rreqs[i].source); lua_setfield(lua, -2, "copy");
        lua_pushinteger(lua, static_cast<lua_Integer>(rreqs[i].ordinal)); lua_setfield(lua, -2, "ordinal");
        lua_rawseti(lua, -2, static_cast<lua_Integer>(i + 1));
    }

    lua_sethook(lua, stock_budget, LUA_MASKCOUNT, 20000000);
    const auto result = lua_pcall(lua, 4, 1, 0);
    lua_sethook(lua, nullptr, 0, 0);
    if (result != LUA_OK) {
        if (lua_isstring(lua, -1))
            std::cerr << lua_tostring(lua, -1) << '\n';
        end_duel(handle);
        return 6;
    }
    if (lua_isstring(lua, -1))
        std::cout << lua_tostring(lua, -1);
    std::cout << "end\n";
    end_duel(handle);
    return 0;
}

static int read_stock(const char* shim, uint32_t* seed) {
    int main_count, extra_count, queries;
    bool alternate;
    while (std::cin >> main_count >> extra_count >> queries >> alternate) {
        if (main_count < 0 || main_count > 75 || extra_count < 0 || extra_count > 30 || queries < 0 || queries > 512)
            return 7;
        std::vector<uint32_t> stock(main_count + extra_count);
        for (auto& code : stock)
            if (!(std::cin >> code) || rows.find(code) == rows.end())
                return 7;
        for (int i = 0; i < queries; ++i) {
            int source, location;
            size_t ordinal;
            if (!(std::cin >> source >> ordinal >> location) || source < 1 || source > static_cast<int>(stock.size()))
                return 7;
            diagnostics.clear();
            const auto handle = create_duel_v2(seed);
            if (!handle)
                return 5;
            fusion_stock(handle, shim, stock, main_count, source, ordinal, location, alternate);
            end_duel(handle);
        }
    }
    return std::cin.eof() ? 0 : 7;
}

int main(int argc, char** argv) {
    if (argc != 3 && argc != 4 && !(argc == 5 && std::string(argv[3]) == "--summon-stock"))
        return 2;
    script_root = fs::canonical(argv[1]);
    std::ifstream cards(argv[2]);
    uint64_t setcodes;
    uint32_t code;
    card_data row{};
    while (cards >> code >> row.alias >> setcodes >> row.type >> row.level
                 >> row.attribute >> row.race >> row.attack >> row.defense
                 >> row.lscale >> row.rscale >> row.link_marker >> row.rule_code) {
        row.code = code;
        write_setcode(row.setcode, setcodes);
        rows.emplace(code, row);
    }
    if (rows.empty() || !cards.eof())
        return 3;
    set_script_reader(locked_script);
    set_card_reader(locked_card);
    set_message_handler(note_diagnostic);
    uint32_t seed[] = {7, 8, 9, 10, 11, 12, 13, 14};
    if (argc == 5)
        return run_summon_stock(argv[4], seed);
    if (argc == 4)
        return read_stock(argv[3], seed);
    while (std::cin >> code) {
        if (rows.find(code) == rows.end()) {
            std::cerr << "card absent from pinned data: " << code << '\n';
            return 4;
        }
        diagnostics.clear();
        const intptr_t handle = create_duel_v2(seed);
        if (!handle)
            return 5;
        duel* engine = reinterpret_cast<duel*>(handle);
        card* printed = nullptr;
        const auto effects = registrations(engine, code, printed);
        if (printed->data.code != code)
            return 6;
        std::cout << "card\t" << code << '\t' << printed->data.get_original_code()
                  << '\t' << printed->data.get_duel_code() << '\t' << diagnostics.size()
                  << '\t' << effects.size() << '\n';
        for (const auto& message : diagnostics)
            std::cout << "diagnostic\t" << message << '\n';
        for (effect* registered : effects) {
            const bool on_card = printed->initial_effect.find(registered) != printed->initial_effect.end();
            write_rule_declaration(std::cout, engine->lua->lua_state, registered, on_card);
            std::cout << "meta\t" << registered->flag[0] << '\t' << registered->flag[1] << '\t';
            if (registered->label.empty()) {
                std::cout << '-';
            } else {
                for (size_t li = 0; li < registered->label.size(); ++li) {
                    if (li) std::cout << ',';
                    std::cout << registered->label[li];
                }
            }
            std::cout << '\n';
        }
        end_duel(handle);
    }
}
