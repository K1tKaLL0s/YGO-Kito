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
    if (argc != 3 && argc != 4)
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
        }
        end_duel(handle);
    }
}
