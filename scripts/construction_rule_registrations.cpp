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
#include "lua.h"
#include "ocgapi.h"

namespace fs = std::filesystem;

static std::unordered_map<uint32_t, card_data> rows;
static fs::path script_root;
static std::unordered_map<std::string, std::vector<byte>> script_bytes;
static std::vector<std::string> diagnostics;

static byte* locked_script(const char* name, int* length) {
    std::string relative(name);
    if (relative.starts_with("./script/"))
        relative.erase(0, 9);
    else if (relative.starts_with("script/"))
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

static void print_callback(lua_State* state, int reference) {
    lua_Debug info{};
    if (reference) {
        lua_rawgeti(state, LUA_REGISTRYINDEX, reference);
        if (lua_getinfo(state, ">S", &info)) {
            std::cout << '\t' << info.short_src << '\t' << info.linedefined << '\t' << info.lastlinedefined;
            return;
        }
    }
    std::cout << (reference ? "\t?\t0\t0" : "\t-\t0\t0");
}

int main(int argc, char** argv) {
    if (argc != 3)
        return 2;
    script_root = fs::canonical(argv[1]);
    std::ifstream cards(argv[2]);
    uint64_t setcodes;
    uint32_t code;
    card_data row;
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
    while (std::cin >> code) {
        if (!rows.contains(code))
            return 4;
        diagnostics.clear();
        const intptr_t handle = create_duel_v2(seed);
        if (!handle)
            return 5;
        duel* engine = reinterpret_cast<duel*>(handle);
        const auto& field = engine->game_field->effects.indexer;
        std::unordered_set<effect*> earlier;
        for (const auto& entry : field)
            earlier.insert(entry.first);
        card* printed = engine->new_card(code);
        std::vector<effect*> effects(printed->initial_effect.begin(), printed->initial_effect.end());
        for (const auto& entry : field)
            if (!earlier.contains(entry.first) && !printed->initial_effect.contains(entry.first))
                effects.push_back(entry.first);
        std::sort(effects.begin(), effects.end(), [](effect* a, effect* b) { return a->ref_handle < b->ref_handle; });
        if (printed->data.code != code)
            return 6;
        std::cout << "card\t" << code << '\t' << printed->data.get_original_code()
                  << '\t' << printed->data.get_duel_code() << '\t' << diagnostics.size()
                  << '\t' << effects.size() << '\n';
        for (const auto& message : diagnostics)
            std::cout << "diagnostic\t" << message << '\n';
        for (effect* registered : effects) {
            std::cout << "registration\t" << (printed->initial_effect.contains(registered) ? "card" : "field")
                      << '\t' << registered->type << '\t' << registered->code << '\t' << registered->range
                      << '\t' << registered->description << '\t' << registered->category << '\t' << registered->count_code;
            auto* state = engine->lua->lua_state;
            print_callback(state, registered->condition);
            print_callback(state, registered->cost);
            print_callback(state, registered->target);
            print_callback(state, registered->operation);
            print_callback(state, registered->is_flag(EFFECT_FLAG_FUNC_VALUE) ? registered->value : 0);
            std::cout << '\n';
        }
        end_duel(handle);
    }
}
