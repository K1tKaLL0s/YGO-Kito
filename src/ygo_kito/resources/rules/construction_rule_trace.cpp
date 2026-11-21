// Observe the chain at native message boundaries. The locked library still
// advances the duel and produces every response and message itself.
#include <cstddef>
#include <cstdint>
#include <sstream>
#include <string>
#include <unordered_map>

#include "card.h"
#include "duel.h"
#include "field.h"
#include "group.h"
#include "interpreter.h"
#include "ocgapi.h"
#include "construction_rule_effect.h"
#include "construction_rule_guards.h"

namespace {
struct Trace {
    Trace(intptr_t duel_handle, uint8_t seat) : handle(duel_handle), seat(seat),
            guards(*reinterpret_cast<duel*>(handle), seat) {
        for (const auto* entity : reinterpret_cast<const duel*>(handle)->cards) {
            if (entity->owner <= 1 && entity->data.code)
                stock.emplace(entity->cardid, entity->current.location);
        }
    }
    intptr_t handle;
    uint8_t seat;
    construction_rule_guards::Observer guards;
    std::unordered_map<uint64_t, uint16_t> stock;
    std::string rows;
    bool failed = false;
};

uint32_t word(const byte* bytes) {
    return uint32_t(bytes[0]) | uint32_t(bytes[1]) << 8 | uint32_t(bytes[2]) << 16 | uint32_t(bytes[3]) << 24;
}

void write_entity(std::ostream& out, const Trace& trace, const card& entity) {
    const auto source = trace.stock.find(entity.cardid);
    out << '\t' << entity.cardid << '\t' << unsigned(entity.owner) << '\t'
        << (source == trace.stock.end() ? 0 : source->second);
}

void capture_moves(Trace& trace, const duel& engine, std::size_t index) {
    const auto& buffer = engine.message_buffer;
    constexpr std::size_t movement_size = 17;
    std::ostringstream out;
    for (std::size_t offset = 0; offset + movement_size <= buffer.size() && buffer[offset] == MSG_MOVE;
            offset += movement_size, ++index) {
        const auto* bytes = buffer.data() + offset;
        const auto code = word(bytes + 1);
        const auto* from = bytes + 5;
        const auto* to = bytes + 9;
        const auto reason = word(bytes + 13);
        auto* entity = engine.game_field->get_field_card(to[0], to[1], to[2]);
        if (!entity || entity->data.code != code || entity->get_info_location() != word(to))
            continue;
        auto* causing_rule = entity->current.reason_effect;
        uint16_t chain_id = 0;
        if (causing_rule) {
            for (const auto& link : engine.game_field->core.current_chain) {
                if (link.triggering_effect != causing_rule)
                    continue;
                if (chain_id) {
                    chain_id = 0;
                    break;
                }
                chain_id = link.chain_id;
            }
        }
        const bool public_destination = to[1] == LOCATION_GRAVE ||
            ((to[1] & (LOCATION_ONFIELD | LOCATION_REMOVED | LOCATION_EXTRA)) && (to[3] & POS_FACEUP));
        const auto operation = trace.guards.operation(chain_id);
        out << "move\t" << index << '\t' << unsigned(from[0]) << '\t' << unsigned(from[1]) << '\t'
            << unsigned(from[2]) << '\t' << unsigned(from[3]) << '\t' << unsigned(to[0]) << '\t'
            << unsigned(to[1]) << '\t' << unsigned(to[2]) << '\t' << unsigned(to[3]) << '\t'
            << reason << '\t' << (entity->owner == trace.seat || public_destination ? code : 0) << '\t' << chain_id
            << '\t' << entity->summon_info << '\t' << operation.id << '\t' << operation.stage;
        write_entity(out, trace, *entity);
        out << '\n';
    }
    trace.rows.append(out.str());
}

void capture(Trace& trace, std::size_t index) {
    auto* engine = reinterpret_cast<duel*>(trace.handle);
    const auto& buffer = engine->message_buffer;
    if (buffer.empty())
        return;
    const auto kind = buffer.front();
    std::size_t offset;
    switch (kind) {
    case MSG_MOVE: capture_moves(trace, *engine, index); return;
    case MSG_CHAINING: offset = 16; break;
    case MSG_CHAINED:
    case MSG_CHAIN_SOLVING:
    case MSG_CHAIN_SOLVED: offset = 1; break;
    default: return;
    }
    const auto& links = engine->game_field->core.current_chain;
    if (buffer.size() <= offset || !buffer[offset] || buffer[offset] > links.size()) {
        trace.failed = true;
        return;
    }
    const auto& link = links[buffer[offset] - 1];
    const auto* rule = link.triggering_effect;
    if (!rule || !rule->handler || link.chain_count != buffer[offset]) {
        trace.failed = true;
        return;
    }
    const auto* handler = rule->get_handler();
    if (!handler) {
        trace.failed = true;
        return;
    }
    std::ostringstream out;
    out << "link\t" << index << '\t' << unsigned(kind) << '\t' << unsigned(link.chain_count) << '\t'
        << handler->data.code << '\t' << unsigned(link.triggering_player) << '\t'
        << (rule->owner ? rule->owner->data.code : 0) << '\t' << unsigned(link.triggering_location) << '\t'
        << unsigned(link.triggering_sequence) << '\t' << link.evt.event_code << '\t' << bool(link.replace_op)
        << '\t' << link.chain_id;
    write_entity(out, trace, *handler);
    out << '\n';
    write_rule_declaration(out, engine->lua->lua_state, rule, !rule->is_flag(EFFECT_FLAG_FIELD_ONLY));
    if (kind == MSG_CHAINED && link.target_cards) {
        for (const auto* target : link.target_cards->container) {
            const auto& state = target->current;
            const bool public_target = state.location == LOCATION_GRAVE ||
                ((state.location & (LOCATION_ONFIELD | LOCATION_REMOVED | LOCATION_EXTRA)) && (state.position & POS_FACEUP));
            out << "target\t" << index << '\t' << unsigned(state.controler) << '\t' << unsigned(state.location)
                << '\t' << unsigned(state.sequence) << '\t' << unsigned(state.position) << '\t'
                << (target->owner == trace.seat || public_target ? target->data.code : 0);
            write_entity(out, trace, *target);
            out << '\n';
        }
    }
    trace.rows.append(out.str());
}
}

extern "C" void* ygo_rule_trace_start(intptr_t handle, uint8_t seat) {
    try {
        return handle && seat < 2 ? new Trace(handle, seat) : nullptr;
    } catch (...) {
        return nullptr;
    }
}

extern "C" uint32_t ygo_rule_trace_process(intptr_t handle, void* opaque, std::size_t index) {
    auto& trace = *static_cast<Trace*>(opaque);
    trace.guards.enter(index);
    const auto result = process(handle);
    trace.guards.leave();
    if (trace.handle == handle && !trace.failed) {
        try {
            trace.rows.append(trace.guards.take());
            capture(trace, index);
        } catch (...) {
            trace.failed = true;
        }
    }
    return result;
}

extern "C" const char* ygo_rule_trace_read(const void* opaque) {
    const auto& trace = *static_cast<const Trace*>(opaque);
    return trace.failed ? nullptr : trace.rows.c_str();
}

extern "C" uint8_t ygo_rule_trace_guard_status(const void* opaque) {
    return static_cast<const Trace*>(opaque)->guards.status();
}

extern "C" void ygo_rule_trace_end(void* opaque) {
    delete static_cast<Trace*>(opaque);
}
