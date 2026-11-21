// Observe the chain at native message boundaries. The locked library still
// advances the duel and produces every response and message itself.
#include <array>
#include <cstddef>
#include <cstdint>
#include <sstream>
#include <string>
#include <unordered_map>
#include <vector>

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
    std::array<std::vector<card*>, 2> decks_before_message;
    std::vector<byte> message;
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

void capture_move(Trace& trace, const duel& engine, std::size_t index, const byte* bytes) {
    const auto code = word(bytes + 1);
    const auto* from = bytes + 5;
    const auto* to = bytes + 9;
    const auto reason = word(bytes + 13);
    card* entity = nullptr;
    if (from[0] < 2 && from[0] == to[0] && from[1] == LOCATION_DECK && to[1] == LOCATION_DECK) {
        auto& order = trace.decks_before_message[from[0]];
        // PROCESSOR_SORT_DECK uses a zero-code, identical-slot notice to
        // refresh the client. It carries neither a transfer nor an entity.
        if (code == 0 && word(from) == word(to) && reason == REASON_EFFECT) {
            trace.rows.append("deck-order\t" + std::to_string(index) + '\n');
            order.clear();
            return;
        }
        // Successive real insertions can shift an earlier destination before
        // the buffer reaches the decoder. Follow the native positions in order.
        if (from[2] < order.size() && to[2] < order.size() && order[from[2]]->data.code == code) {
            entity = order[from[2]];
            order.erase(order.begin() + from[2]);
            order.insert(order.begin() + to[2], entity);
            constexpr uint32_t except_sequence = 0xff00ffff;
            if ((entity->get_info_location() & except_sequence) != (word(to) & except_sequence))
                return;
        } else {
            order.clear();
            return;
        }
    } else {
        if (from[0] < 2 && from[1] == LOCATION_DECK)
            trace.decks_before_message[from[0]].clear();
        if (to[0] < 2 && to[1] == LOCATION_DECK)
            trace.decks_before_message[to[0]].clear();
        entity = engine.game_field->get_field_card(to[0], to[1], to[2]);
        const uint32_t shown = word(to) & ~(to[1] & LOCATION_ONFIELD ? uint32_t(POS_REVEAL) << 24 : 0);
        if (!entity || entity->data.code != code || entity->get_info_location() != shown)
            return;
    }
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
    std::ostringstream out;
    out << "move\t" << index << '\t' << unsigned(from[0]) << '\t' << unsigned(from[1]) << '\t'
        << unsigned(from[2]) << '\t' << unsigned(from[3]) << '\t' << unsigned(to[0]) << '\t'
        << unsigned(to[1]) << '\t' << unsigned(to[2]) << '\t' << unsigned(to[3]) << '\t'
        << reason << '\t' << (entity->owner == trace.seat || public_destination ? code : 0) << '\t' << chain_id
        << '\t' << entity->summon_info << '\t' << operation.id << '\t' << operation.stage;
    write_entity(out, trace, *entity);
    out << '\n';
    trace.rows.append(out.str());
}

void capture(Trace& trace, std::size_t index, std::size_t start) {
    auto* engine = reinterpret_cast<duel*>(trace.handle);
    if (start >= trace.message.size())
        return;
    const auto* bytes = trace.message.data() + start;
    const auto size = trace.message.size() - start;
    const auto kind = bytes[0];
    std::size_t offset;
    switch (kind) {
    case MSG_MOVE:
        if (size >= 17)
            capture_move(trace, *engine, index, bytes);
        return;
    case MSG_CHAINING: offset = 16; break;
    case MSG_CHAINED:
    case MSG_CHAIN_SOLVING:
    case MSG_CHAIN_SOLVED: offset = 1; break;
    default: return;
    }
    const auto& links = engine->game_field->core.current_chain;
    if (size <= offset || !bytes[offset] || bytes[offset] > links.size())
        return;
    const auto& link = links[bytes[offset] - 1];
    const auto* rule = link.triggering_effect;
    if (!rule || !rule->handler || link.chain_count != bytes[offset])
        return;
    const auto* handler = rule->get_handler();
    if (!handler)
        return;
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
    const auto* engine = reinterpret_cast<const duel*>(handle);
    if (trace.handle == handle && !trace.failed) {
        try {
            for (uint8_t seat = 0; seat < 2; ++seat) {
                const auto& deck = engine->game_field->player[seat].list_main;
                trace.decks_before_message[seat].assign(deck.begin(), deck.end());
            }
        } catch (...) {
            trace.failed = true;
        }
    }
    trace.guards.enter(index);
    const auto result = process(handle);
    trace.guards.leave();
    if (trace.handle == handle && !trace.failed) {
        try {
            trace.rows.append(trace.guards.take());
            trace.message = engine->message_buffer;
        } catch (...) {
            trace.failed = true;
        }
    }
    return result;
}

extern "C" void ygo_rule_trace_message(void* opaque, std::size_t index, std::size_t offset) {
    auto& trace = *static_cast<Trace*>(opaque);
    if (trace.failed)
        return;
    try {
        capture(trace, index, offset);
    } catch (...) {
        trace.failed = true;
    }
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
