#pragma once

#include <ostream>
#include <string_view>

#include "effect.h"
#include "lua.h"

inline void write_rule_callback(std::ostream& out, lua_State* state, int reference) {
    lua_Debug info{};
    if (reference) {
        lua_rawgeti(state, LUA_REGISTRYINDEX, reference);
        if (lua_getinfo(state, ">S", &info)) {
            out << '\t' << std::string_view(info.source, info.srclen)
                << '\t' << info.linedefined << '\t' << info.lastlinedefined;
            return;
        }
    }
    out << (reference ? "\t?\t0\t0" : "\t-\t0\t0");
}

inline void write_rule_declaration(std::ostream& out, lua_State* state, const effect* registered, bool on_card) {
    out << "registration\t" << (on_card ? "card" : "field")
        << '\t' << registered->type << '\t' << registered->code << '\t' << registered->range
        << '\t' << registered->description << '\t' << registered->category << '\t' << registered->count_code
        << '\t' << (registered->is_flag(EFFECT_FLAG_COUNT_LIMIT) ? unsigned(registered->count_limit_max) : 0)
        << '\t' << bool(registered->is_flag(EFFECT_FLAG_NO_TURN_RESET));
    write_rule_callback(out, state, registered->condition);
    write_rule_callback(out, state, registered->cost);
    write_rule_callback(out, state, registered->target);
    write_rule_callback(out, state, registered->operation);
    write_rule_callback(out, state, registered->is_flag(EFFECT_FLAG_FUNC_VALUE) ? registered->value : 0);
    out << '\n';
}
