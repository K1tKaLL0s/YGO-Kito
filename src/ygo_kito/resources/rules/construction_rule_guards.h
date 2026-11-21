#pragma once

#include <cstddef>
#include <sstream>
#include <string>
#include <string_view>
#include <unordered_map>

#include "card.h"
#include "duel.h"
#include "field.h"
#include "interpreter.h"
#include "construction_rule_effect.h"

namespace construction_rule_guards {

class Observer {
    struct Guard {
        std::string_view role;
        std::string declaration;
        uint64_t entity;
        uint32_t card;
        uint8_t position;
        uint16_t zone;
        uint16_t phase;
        uint16_t turn;
    };

public:
    struct Operation {
        uint32_t id{};
        uint32_t stage{};
        std::string_view method;
    };

    Observer(duel& engine, uint8_t seat) : engine(engine), seat(seat) {
        auto* state = engine.lua->lua_state;
        installed = !lua_gethook(state);
        if (installed) {
            lua_getglobal(state, "Duel");
            if (lua_istable(state, -1)) {
                for (const char* name : {"BreakEffect", "SendtoGrave", "SendtoDeck", "SendtoHand", "DiscardDeck",
                        "DiscardHand", "Destroy", "Release", "Remove", "SpecialSummon", "SpecialSummonStep",
                        "SpecialSummonComplete", "Draw", "Damage", "Recover", "Overlay", "MoveToField", "SSet",
                        "GetControl", "SwapControl", "Equip", "ChangePosition", "NegateActivation", "NegateEffect"}) {
                    lua_getfield(state, -1, name);
                    if (auto method = lua_tocfunction(state, -1))
                        operations.emplace(method, name);
                    lua_pop(state, 1);
                }
            }
            lua_pop(state, 1);
            lua_sethook(state, hook, LUA_MASKCALL | LUA_MASKRET, 0);
        }
    }

    ~Observer() {
        if (!installed)
            return;
        lua_sethook(engine.lua->lua_state, nullptr, 0, 0);
        for (const auto& entry : engine.lua->coroutines)
            lua_sethook(entry.second.first, nullptr, 0, 0);
    }

    void enter(std::size_t index) {
        message_index = index;
        if (installed && !failed)
            active = this;
    }

    void leave() {
        active = nullptr;
        open.clear();
    }

    std::string take() {
        std::string result;
        result.swap(rows);
        return result;
    }

    uint8_t status() const {
        return !installed ? 1 : failed ? 2 : 0;
    }

    Operation operation(uint16_t chain) const {
        const auto found = sites.find(chain);
        return found == sites.end() ? Operation{} : found->second;
    }

private:
    static inline thread_local Observer* active = nullptr;
    duel& engine;
    uint8_t seat;
    std::size_t message_index{};
    bool installed = false;
    bool failed = false;
    std::string rows;
    std::unordered_map<const void*, Guard> open;
    std::unordered_map<lua_CFunction, std::string_view> operations;
    std::unordered_map<uint16_t, Operation> sites;
    uint32_t next_operation{};

    void read_operation(lua_State* state, lua_Debug* frame, const field& field, const effect* rule) {
        const auto& processor = field.core;
        if (processor.units.empty() || processor.units.front().type != PROCESSOR_EXECUTE_OPERATION ||
            processor.units.front().peffect != rule || processor.current_chain.empty() ||
            processor.current_chain.back().triggering_effect != rule || !lua_getinfo(state, "f", frame))
            return;
        auto method = operations.find(lua_tocfunction(state, -1));
        lua_pop(state, 1);
        if (method == operations.end())
            return;
        const auto chain = processor.current_chain.back().chain_id;
        auto& site = sites[chain];
        if (method->second == "BreakEffect") {
            ++site.stage;
            return;
        }
        site.id = ++next_operation;
        site.method = method->second;
        std::ostringstream out;
        out << "operation\t" << message_index << '\t' << chain << '\t' << site.id << '\t'
            << site.stage << '\t' << site.method << '\n';
        rows.append(out.str());
    }

    static std::string_view role_for(lua_State* state, lua_Debug* frame, const effect* current) {
        if (!lua_getlocal(state, frame, 1))
            return {};
        const bool owner = lua_type(state, -1) == LUA_TUSERDATA && lua_rawlen(state, -1) == sizeof(effect*) &&
            *static_cast<effect**>(lua_touserdata(state, -1)) == current;
        lua_pop(state, 1);
        if (!owner || !lua_getinfo(state, "f", frame))
            return {};
        std::string_view role;
        for (const auto& [reference, name] : {std::pair(current->condition, "condition"),
                 std::pair(current->cost, "cost"), std::pair(current->target, "target")}) {
            if (!reference)
                continue;
            lua_rawgeti(state, LUA_REGISTRYINDEX, reference);
            const bool same = lua_rawequal(state, -1, -2);
            lua_pop(state, 1);
            if (same) {
                role = name;
                break;
            }
        }
        lua_pop(state, 1);
        if (role == "cost" || role == "target") {
            // The core passes chk=0 for an availability check and chk=1
            // for an actual payment or committed target selection.
            if (!lua_getlocal(state, frame, 9))
                return {};
            const bool checking = lua_isinteger(state, -1) && lua_tointeger(state, -1) == 0;
            lua_pop(state, 1);
            if (!checking)
                return {};
        }
        return role;
    }

    void read_frame(lua_State* state, lua_Debug* frame) {
        if (frame->event == LUA_HOOKRET) {
            const auto found = open.find(frame->i_ci);
            if (found == open.end() || !lua_getinfo(state, "r", frame))
                return;
            bool passed = false;
            if (frame->ntransfer) {
                if (!lua_getlocal(state, frame, frame->ftransfer)) {
                    open.erase(found);
                    return;
                }
                passed = lua_toboolean(state, -1);
                lua_pop(state, 1);
            }
            const auto& guard = found->second;
            std::ostringstream out;
            out << "guard\t" << message_index << '\t' << guard.entity << '\t' << guard.card
                << '\t' << unsigned(seat) << '\t' << guard.turn << '\t' << guard.phase << '\t'
                << guard.zone << '\t' << unsigned(guard.position) << '\t' << guard.role << '\t'
                << passed << '\n' << guard.declaration;
            rows.append(out.str());
            open.erase(found);
            return;
        }
        if (open.find(frame->i_ci) != open.end())
            return;
        auto* field = engine.game_field;
        auto* rule = field->core.reason_effect;
        if (!rule || !(rule->type & EFFECT_TYPE_ACTIONS) || field->core.reason_player != seat)
            return;
        const auto* handler = rule->get_handler();
        if (!handler || handler->owner != seat)
            return;
        read_operation(state, frame, *field, rule);
        const auto role = role_for(state, frame, rule);
        if (role.empty())
            return;
        std::ostringstream out;
        write_rule_declaration(out, state, rule, !rule->is_flag(EFFECT_FLAG_FIELD_ONLY));
        open.emplace(frame->i_ci, Guard{role, out.str(), handler->cardid, handler->data.code,
            handler->current.position, handler->current.location, field->infos.phase, field->infos.turn_id});
    }

    static void hook(lua_State* state, lua_Debug* frame) {
        if (active && !active->failed && lua_checkstack(state, 4)) {
            try {
                active->read_frame(state, frame);
            } catch (...) {
                active->failed = true;
            }
        }
    }
};
}
