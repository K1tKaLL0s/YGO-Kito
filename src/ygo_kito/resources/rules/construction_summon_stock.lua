-- Evaluate locked period core summoning procedures and monster entry rules
-- over distinct physical copies from the active deck view.
return function(helpers, stock_entries, fusion_reqs, ritual_reqs)
	local out = {}
	local own_dummy1 = helpers.new_dummy()
	local opp_dummy1 = helpers.new_dummy()
	local opp_dummy2 = helpers.new_dummy()
	local g0 = Group.CreateGroup()

	local function emit(line)
		out[#out + 1] = line
	end

	local function clear_board()
		for _, e in ipairs(stock_entries) do
			if e.card:GetLocation() ~= 0 then
				helpers.remove(e.card)
			end
		end
		if own_dummy1:GetLocation() ~= 0 then helpers.remove(own_dummy1) end
		if opp_dummy1:GetLocation() ~= 0 then helpers.remove(opp_dummy1) end
		if opp_dummy2:GetLocation() ~= 0 then helpers.remove(opp_dummy2) end
		helpers.set_phase(1, 0, PHASE_MAIN1)
	end

	local function bitcount(n)
		local c = 0
		while n > 0 do
			if n & 1 ~= 0 then c = c + 1 end
			n = n >> 1
		end
		return c
	end

	local function get_link_markers(c)
		local m = 0
		for _, bit in ipairs({0x001, 0x002, 0x004, 0x008, 0x020, 0x040, 0x080, 0x100}) do
			if c:IsLinkMarker(bit) then m = m | bit end
		end
		return m
	end

	-- Group stock entries by section and unique code (keeping physical copies)
	local by_code = {}
	local code_order = {}
	local main_monster_codes = {}
	local extra_monster_codes = {}
	local extra_pend_codes = {}
	local main_pend_codes = {}
	local ritual_monster_codes = {}

	for _, e in ipairs(stock_entries) do
		local c = e.code
		if not by_code[c] then
			by_code[c] = { code = c, section = e.section, entries = {}, card = e.card }
			code_order[#code_order + 1] = c
			local tp = e.card:GetType()
			if tp & TYPE_MONSTER ~= 0 then
				if e.section == "main" then
					main_monster_codes[#main_monster_codes + 1] = c
					if tp & TYPE_PENDULUM ~= 0 then
						main_pend_codes[#main_pend_codes + 1] = c
					end
					if tp & TYPE_RITUAL ~= 0 then
						ritual_monster_codes[#ritual_monster_codes + 1] = c
					end
				else
					extra_monster_codes[#extra_monster_codes + 1] = c
					if tp & TYPE_PENDULUM ~= 0 then
						extra_pend_codes[#extra_pend_codes + 1] = c
					end
				end
			end
		end
		local list = by_code[c].entries
		list[#list + 1] = e
	end

	local function join_copies(entries, delim)
		local parts = {}
		for _, e in ipairs(entries) do
			parts[#parts + 1] = tostring(e.copy)
		end
		return table.concat(parts, delim or ",")
	end

	-- Enumerate multisets over `items` (each item has .entries, .cap, etc.)
	-- `accept(chosen_entries, item_counts)`
	local function enum_multisets(items, k_min, k_max, max_checks, accept)
		local checks = 0
		local visits = 0
		local max_visits = math.max(12000, max_checks * 40)
		local chosen = {}
		local stopped = false
		local function rec(idx, depth)
			if stopped then return end
			if depth >= k_min then
				visits = visits + 1
				if visits > max_visits then
					stopped = true
					return
				end
				local res = accept(chosen)
				if res ~= "skip" then
					checks = checks + 1
					if checks >= max_checks then
						stopped = true
						return
					end
				end
				if res == false then
					stopped = true
					return
				end
			end
			if depth == k_max then return end
			for i = idx, #items do
				local item = items[i]
				local used = item._used or 0
				if used < #item.entries then
					item._used = used + 1
					chosen[depth + 1] = item.entries[item._used]
					rec(i, depth + 1)
					chosen[depth + 1] = nil
					item._used = used
					if stopped then return end
				end
			end
		end
		for _, it in ipairs(items) do it._used = 0 end
		rec(1, 0)
		for _, it in ipairs(items) do it._used = nil end
		return stopped
	end

	local function safe_call(fn, ...)
		if not fn then return false end
		local ok, res = pcall(fn, ...)
		return ok and not not res
	end

	-- 1. Monster Summon Rules & Main Deck Inherent Special Summon Procs
	local has_ss_proc = {}
	for _, code in ipairs(code_order) do
		local grp = by_code[code]
		local e0 = grp.entries[1]
		local card = e0.card
		clear_board()
		local ctype = card:GetType()
		if ctype & TYPE_MONSTER ~= 0 then
			local cannot_ns = (not card:IsSummonableCard()) or (card:IsHasEffect(EFFECT_CANNOT_SUMMON) ~= nil) or (grp.section == "extra")
			local has_revive = (card:IsHasEffect(EFFECT_REVIVE_LIMIT) ~= nil)
			local nomi = false
			for _, eff in ipairs(e0.effects) do
				if eff.scope == "card" and eff.code == EFFECT_SPSUMMON_CONDITION and eff.type & EFFECT_TYPE_SINGLE ~= 0 then
					nomi = true
				end
			end
			local lv = card:GetLevel()
			local rank = card:GetRank()
			local link = card:GetLink()
			local is_tuner = card:IsType(TYPE_TUNER)
			local is_flip = card:IsType(TYPE_FLIP)
			local is_pend = card:IsType(TYPE_PENDULUM)
			local pend_lv = card.pendulum_level or lv
			local markers = get_link_markers(card)
			local down_arrows = bitcount(markers & 0x007)
			local lscale, rscale = 0, 0
			if is_pend then
				lscale = card:GetLeftScale()
				rscale = card:GetRightScale()
			end
			emit(string.format(
				"monster_rule\t%d\t%d\t%d\t%d\t%d\t%d\t%d\t%d\t%d\t%d\t%d\t%d\t%d\t%d\t%d",
				e0.copy, cannot_ns and 1 or 0, nomi and 1 or 0, has_revive and 1 or 0,
				lv, rank, link, is_tuner and 1 or 0, is_flip and 1 or 0, is_pend and 1 or 0,
				pend_lv, markers, down_arrows, lscale, rscale
			))
			if grp.section == "main" then
				for _, eff in ipairs(e0.effects) do
					if eff.scope == "card" and eff.code == EFFECT_SPSUMMON_PROC and eff.condition then
						local range = eff.range
						local loc = (range & LOCATION_GRAVE ~= 0 and range & LOCATION_HAND == 0) and LOCATION_GRAVE or LOCATION_HAND
						clear_board()
						helpers.place(card, 0, 0, loc, 0, POS_FACEUP_ATTACK, false, false)
						local empty_ok = safe_call(eff.condition, eff.effect, card)
						helpers.place(opp_dummy1, 1, 1, LOCATION_MZONE, 0, POS_FACEUP_ATTACK, false, true)
						local opp_ok = safe_call(eff.condition, eff.effect, card)
						local with_own_ok = false
						if empty_ok or opp_ok then
							clear_board()
							helpers.place(card, 0, 0, loc, 0, POS_FACEUP_ATTACK, false, false)
							helpers.place(own_dummy1, 0, 0, LOCATION_MZONE, 0, POS_FACEUP_ATTACK, false, true)
							local own0_ok = safe_call(eff.condition, eff.effect, card)
							helpers.place(opp_dummy1, 1, 1, LOCATION_MZONE, 0, POS_FACEUP_ATTACK, false, true)
							local own1_ok = safe_call(eff.condition, eff.effect, card)
							helpers.place(opp_dummy2, 1, 1, LOCATION_MZONE, 1, POS_FACEUP_ATTACK, false, true)
							local own2_ok = safe_call(eff.condition, eff.effect, card)
							with_own_ok = own0_ok or own1_ok or own2_ok
							if not with_own_ok and #grp.entries >= 2 then
								clear_board()
								helpers.place(card, 0, 0, loc, 0, POS_FACEUP_ATTACK, false, false)
								helpers.place(grp.entries[2].card, 0, 0, LOCATION_MZONE, 0, POS_FACEUP_ATTACK, false, true)
								local same0_ok = safe_call(eff.condition, eff.effect, card)
								helpers.place(opp_dummy1, 1, 1, LOCATION_MZONE, 0, POS_FACEUP_ATTACK, false, true)
								local same1_ok = safe_call(eff.condition, eff.effect, card)
								helpers.place(opp_dummy2, 1, 1, LOCATION_MZONE, 1, POS_FACEUP_ATTACK, false, true)
								local same2_ok = safe_call(eff.condition, eff.effect, card)
								with_own_ok = same0_ok or same1_ok or same2_ok
							end
							local rank = with_own_ok and 1 or 2
							if not has_ss_proc[code] or rank < has_ss_proc[code] then
								has_ss_proc[code] = rank
							end
						end
						emit(string.format(
							"inherent_ss\t%d\t%d\t%d\t%d\t%d\t%d",
							e0.copy, eff.ordinal, range, empty_ok and 1 or 0, opp_ok and 1 or 0, with_own_ok and 1 or 0
						))
					end
				end
			end
		end
	end

	-- Deterministic order prioritizing Special-Summonable / Tuner / Extra / Pendulum monsters
	local all_monster_codes = {}
	for _, c in ipairs(extra_monster_codes) do all_monster_codes[#all_monster_codes + 1] = c end
	for _, c in ipairs(main_monster_codes) do all_monster_codes[#all_monster_codes + 1] = c end
	table.sort(all_monster_codes, function(a, b)
		local ea, eb = by_code[a], by_code[b]
		local ra = (ea.section == "extra" and 0 or (has_ss_proc[a] or 3))
		local rb = (eb.section == "extra" and 0 or (has_ss_proc[b] or 3))
		if ra ~= rb then return ra < rb end
		return a < b
	end)

	-- Helper: check Extra monster SPSUMMON_PROC on a given MZone group `sg_entries`
	local function place_mzone_group(sg_entries)
		clear_board()
		local g = Group.CreateGroup()
		local seq = 0
		for _, entry in ipairs(sg_entries) do
			if seq >= 5 then
				return nil
			end
			helpers.place(entry.card, 0, 0, LOCATION_MZONE, seq, POS_FACEUP_ATTACK, false, true)
			g:AddCard(entry.card)
			seq = seq + 1
		end
		return g
	end

	-- 2. Material-free / LP-cost Fusion effects (e.g. Instant Fusion)
	local real_pay_lp = Duel.PayLPCost
	for _, req in ipairs(fusion_reqs) do
		local entry = stock_entries[req.copy]
		local eff = entry and entry.effects[req.ordinal + 1]
		if eff and eff.target then
			clear_board()
			Duel.SetLP(0, 8000)
			helpers.place(entry.card, 0, 0, req.location, 0, POS_FACEUP_ATTACK, false, false)
			local cond_ok = (not eff.condition) or safe_call(eff.condition, eff.effect, 0, g0, 0, 0, nil, REASON_EFFECT, 0, 0)
			local cost_ok = cond_ok
			local lp_paid = 0
			if cost_ok and eff.cost then
				cost_ok = safe_call(eff.cost, eff.effect, 0, g0, 0, 0, nil, REASON_EFFECT, 0, 0)
				if cost_ok then
					Duel.PayLPCost = function(p, amt)
						if p == 0 and amt then lp_paid = lp_paid + amt end
					end
					safe_call(eff.cost, eff.effect, 0, g0, 0, 0, nil, REASON_EFFECT, 0, 1)
					Duel.PayLPCost = real_pay_lp
					Duel.SetLP(0, 8000)
				end
			end
			if cost_ok then
				for _, fcode in ipairs(extra_monster_codes) do
					local fe = by_code[fcode].entries[1]
					if fe.card:IsType(TYPE_FUSION) and fe.copy ~= entry.copy then
						helpers.place(fe.card, 0, 0, LOCATION_EXTRA, 0, POS_FACEDOWN_DEFENSE, false, false)
						local ok = safe_call(eff.target, eff.effect, 0, g0, 0, 0, nil, REASON_EFFECT, 0, 0)
						helpers.remove(fe.card)
						if ok then
							emit(string.format("fusion_no_mat\t%d\t%d\t%d", req.qi, fe.copy, lp_paid))
						end
					end
				end
			end
		end
	end

	-- 3. Contact Fusion, Xyz, Synchro, Link procedures over Extra Deck monsters
	local real_get_flag = Duel.GetFlagEffect
	for _, ex_code in ipairs(extra_monster_codes) do
		local ex_grp = by_code[ex_code]
		local ex_entry = ex_grp.entries[1]
		local target = ex_entry.card
		local ttype = target:GetType()

		for _, eff in ipairs(ex_entry.effects) do
			if eff.scope == "card" and eff.code == EFFECT_SPSUMMON_PROC and eff.condition and (eff.range & LOCATION_EXTRA ~= 0) then
				-- Identify proc family from card type + constant SUMMON_TYPE
				if ttype & TYPE_FUSION ~= 0 then
					-- Contact Fusion
					local mat_items = {}
					for _, mc in ipairs(all_monster_codes) do
						local mg = by_code[mc]
						if mc ~= ex_code or #mg.entries > 1 then
							mat_items[#mat_items + 1] = mg
						end
					end
					for _, loc in ipairs({LOCATION_MZONE, LOCATION_GRAVE, LOCATION_HAND}) do
						local accepted = 0
						enum_multisets(mat_items, 1, 3, 250, function(chosen)
							if accepted >= 32 then return false end
							local self_used = 0
							for _, ce in ipairs(chosen) do
								if ce.copy == ex_entry.copy then self_used = self_used + 1 end
							end
							if self_used > 0 then return "skip" end
							if loc == LOCATION_HAND or loc == LOCATION_DECK then
								for _, ce in ipairs(chosen) do
									if ce.section == "extra" then return "skip" end
								end
							end
							clear_board()
							for seq, ce in ipairs(chosen) do
								if seq > 5 then return "skip" end
								helpers.place(ce.card, 0, 0, loc, seq - 1, POS_FACEUP_ATTACK, false, true)
							end
							helpers.place(target, 0, 0, LOCATION_EXTRA, 0, POS_FACEDOWN_DEFENSE, false, false)
							if safe_call(eff.condition, eff.effect, target) then
								accepted = accepted + 1
								local pairs_s = {}
								for _, ce in ipairs(chosen) do
									pairs_s[#pairs_s + 1] = string.format("%d:%d", ce.copy, loc)
								end
								emit(string.format("contact_fusion\t%d\t%d\t%s", ex_entry.copy, eff.ordinal, table.concat(pairs_s, ",")))
							end
							return true
						end)
						if accepted > 0 then break end
					end

				elseif ttype & TYPE_XYZ ~= 0 then
					-- Alternate 1-material overlay check (e.g., Zeus, Utopia Lightning, Downerd)
					local xyz_bases = {}
					for _, mc in ipairs(extra_monster_codes) do
						local mg = by_code[mc]
						if mc ~= ex_code and mg.card:IsType(TYPE_XYZ) then
							xyz_bases[#xyz_bases + 1] = mg.entries[1]
						end
					end
					for _, base_entry in ipairs(xyz_bases) do
						clear_board()
						helpers.place(base_entry.card, 0, 0, LOCATION_MZONE, 0, POS_FACEUP_ATTACK, false, true)
						helpers.place(target, 0, 0, LOCATION_EXTRA, 0, POS_FACEDOWN_DEFENSE, false, false)
						local og = Group.FromCards(base_entry.card)
						local strict_ok = safe_call(eff.condition, eff.effect, target, og, 1, 1)
						if strict_ok then
							emit(string.format("xyz\t%d\t%d\t1\tnone\t1\t%d", ex_entry.copy, eff.ordinal, base_entry.copy))
						else
							local function try_flags(depth, assigned)
								local next_unknown = nil
								Duel.GetFlagEffect = function(p, id)
									if assigned[id] ~= nil then
										return assigned[id]
									end
									if not next_unknown then next_unknown = id end
									return 1
								end
								local ok = safe_call(eff.condition, eff.effect, target, og, 1, 1)
								Duel.GetFlagEffect = real_get_flag
								if ok then
									for _, v in pairs(assigned) do
										if v == 1 then return true end
									end
									return next_unknown ~= nil
								end
								if not next_unknown or depth >= 3 then
									return false
								end
								assigned[next_unknown] = 1
								if try_flags(depth + 1, assigned) then
									assigned[next_unknown] = nil
									return true
								end
								assigned[next_unknown] = 0
								local res0 = try_flags(depth + 1, assigned)
								assigned[next_unknown] = nil
								return res0
							end
							if try_flags(0, {}) then
								local ext_flag = "turn_flag_event"
								for _, reg_eff in ipairs(ex_entry.effects) do
									if reg_eff.scope == "field" then
										if reg_eff.code == EVENT_BATTLED then
											ext_flag = "xyz_monster_battled_this_turn"
											break
										elseif reg_eff.code == EVENT_BATTLE_DESTROYED or reg_eff.code == EVENT_BATTLE_DAMAGE or reg_eff.code == EVENT_ATTACK_ANNOUNCE then
											ext_flag = "battle_event_this_turn"
										end
									end
								end
								emit(string.format("xyz\t%d\t%d\t1\t%s\t1\t%d", ex_entry.copy, eff.ordinal, ext_flag, base_entry.copy))
							end
						end
					end
					-- Standard Xyz material check (2..4 materials)
					local target_rank = target:GetRank()
					local eligible = {}
					for _, mc in ipairs(all_monster_codes) do
						local mg = by_code[mc]
						if mc ~= ex_code then
							clear_board()
							local c0 = mg.entries[1].card
							helpers.place(c0, 0, 0, LOCATION_MZONE, 0, POS_FACEUP_ATTACK, false, true)
							helpers.place(target, 0, 0, LOCATION_EXTRA, 0, POS_FACEDOWN_DEFENSE, false, false)
							if c0:IsCanBeXyzMaterial(target) and (c0:IsXyzLevel(target, target_rank) or c0:IsHasEffect(EFFECT_XYZ_LEVEL) or not c0:IsType(TYPE_XYZ + TYPE_LINK)) then
								eligible[#eligible + 1] = mg
							end
						end
					end
					-- Prefer level-matching first, then Extra/SS-capable before NS-only
					table.sort(eligible, function(a, b)
						local la = (a.card:GetLevel() == target_rank) and 0 or 1
						local lb = (b.card:GetLevel() == target_rank) and 0 or 1
						if la ~= lb then return la < lb end
						local ra = (a.section == "extra" and 0 or (has_ss_proc[a.code] or 3))
						local rb = (b.section == "extra" and 0 or (has_ss_proc[b.code] or 3))
						if ra ~= rb then return ra < rb end
						return a.code < b.code
					end)
					local accepted = 0
					for mat_ct = 2, 4 do
						if accepted >= 96 then break end
						local ct_accepted = 0
						enum_multisets(eligible, mat_ct, mat_ct, 400, function(chosen)
							if accepted >= 96 then return false end
							local g = place_mzone_group(chosen)
							if not g then return "skip" end
							helpers.place(target, 0, 0, LOCATION_EXTRA, 0, POS_FACEDOWN_DEFENSE, false, false)
							if safe_call(eff.condition, eff.effect, target, g, #chosen, #chosen) then
								accepted = accepted + 1
								ct_accepted = ct_accepted + 1
								emit(string.format("xyz\t%d\t%d\t0\tnone\t%d\t%s", ex_entry.copy, eff.ordinal, #chosen, join_copies(chosen)))
							end
							return true
						end)
						-- Once 2-mat normal overlay works, check if 3-mat variant exists only when minc<maxc
						if mat_ct == 2 and ct_accepted > 0 then
							-- Check if a single 3-mat variant is accepted; skip full enumeration unless needed
						end
					end

				elseif ttype & TYPE_SYNCHRO ~= 0 then
					local syn_lv = target:GetLevel()
					local candidates = {}
					for _, mc in ipairs(all_monster_codes) do
						local mg = by_code[mc]
						if mc ~= ex_code then
							clear_board()
							local c0 = mg.entries[1].card
							helpers.place(c0, 0, 0, LOCATION_MZONE, 0, POS_FACEUP_ATTACK, false, true)
							local slv = c0:GetSynchroLevel(target)
							local lv1 = slv & 0xffff
							local lv2 = slv >> 16
							local is_t = c0:IsTuner(target)
							if c0:IsCanBeSynchroMaterial(target) and ((lv1 > 0 and lv1 < syn_lv) or (lv2 > 0 and lv2 < syn_lv)) then
								candidates[#candidates + 1] = {
									code = mc, entries = mg.entries, is_tuner = is_t,
									lv1 = lv1, lv2 = lv2,
								}
							end
						end
					end
					local accepted = 0
					for mat_ct = 2, 4 do
						if accepted >= 48 then break end
						enum_multisets(candidates, mat_ct, mat_ct, 200, function(chosen)
							if accepted >= 48 then return false end
							-- Quick static sum/tuner screen before touching board
							local has_tuner = false
							local min_sum, max_sum = 0, 0
							for _, ce in ipairs(chosen) do
								for _, it in ipairs(candidates) do
									if it.code == ce.code then
										if it.is_tuner then has_tuner = true end
										min_sum = min_sum + it.lv1
										max_sum = max_sum + (it.lv2 > 0 and it.lv2 or it.lv1)
										break
									end
								end
							end
							if min_sum > syn_lv or max_sum < syn_lv or not has_tuner then return "skip" end
							local g = place_mzone_group(chosen)
							if not g then return "skip" end
							helpers.place(target, 0, 0, LOCATION_EXTRA, 0, POS_FACEDOWN_DEFENSE, false, false)
							if safe_call(eff.condition, eff.effect, target, nil, g) then
								accepted = accepted + 1
								local tuners = {}
								for _, ce in ipairs(chosen) do
									for _, it in ipairs(candidates) do
										if it.code == ce.code and it.is_tuner then tuners[#tuners + 1] = ce break end
									end
								end
								emit(string.format("synchro\t%d\t%d\t%s\t%s", ex_entry.copy, eff.ordinal, join_copies(tuners), join_copies(chosen)))
							end
							return true
						end)
					end

				elseif ttype & TYPE_LINK ~= 0 then
					local rating = target:GetLink()
					local markers = get_link_markers(target)
					local down_arrows = bitcount(markers & 0x007)
					clear_board()
					helpers.place(target, 0, 0, LOCATION_MZONE, 5, POS_FACEUP_ATTACK, false, true)
					local linked_mask = target:GetLinkedZone(0)
					clear_board()

					local link_mats = {}
					for _, mc in ipairs(all_monster_codes) do
						local mg = by_code[mc]
						if mc ~= ex_code then
							clear_board()
							local c0 = mg.entries[1].card
							helpers.place(c0, 0, 0, LOCATION_MZONE, 0, POS_FACEUP_ATTACK, false, true)
							if c0:IsCanBeLinkMaterial(target) then
								local cr = (c0:IsType(TYPE_LINK) and c0:GetLink() > 1) and c0:GetLink() or 1
								link_mats[#link_mats + 1] = { code = mc, entries = mg.entries, link_r = cr }
							end
						end
					end
					-- Pre-index link_r by code
					local mat_rating = {}
					for _, it in ipairs(link_mats) do mat_rating[it.code] = it.link_r end
					-- Test smaller material counts first (e.g. Link-2 + 1 before 1+1+1 for Link-3!)
					local accepted = 0
					for mat_ct = 1, math.min(rating, 5) do
						if accepted >= 64 then break end
						enum_multisets(link_mats, mat_ct, mat_ct, 360, function(chosen)
							if accepted >= 64 then return false end
							-- Check if some assignment of 1 or link_r hits exact target rating
							local sums = {[0] = true}
							for _, ce in ipairs(chosen) do
								local r2 = mat_rating[ce.code] or 1
								local next_s = {}
								for s in pairs(sums) do
									if s + 1 <= rating then next_s[s + 1] = true end
									if r2 > 1 and s + r2 <= rating then next_s[s + r2] = true end
								end
								sums = next_s
							end
							if not sums[rating] then return "skip" end
							local g = place_mzone_group(chosen)
							if not g then return "skip" end
							helpers.place(target, 0, 0, LOCATION_EXTRA, 0, POS_FACEDOWN_DEFENSE, false, false)
							if safe_call(eff.condition, eff.effect, target, g, nil, #chosen, #chosen) then
								accepted = accepted + 1
								emit(string.format(
									"link\t%d\t%d\t%d\t%d\t%d\t%d\t%s",
									ex_entry.copy, eff.ordinal, rating, markers, down_arrows, linked_mask, join_copies(chosen)
								))
							end
							return true
						end)
					end
				end
			end
		end
	end

	-- 4. Pendulum Scale pairs -> Hand & Face-up Extra Pendulum targets
	for i = 1, #main_pend_codes do
		local lc = main_pend_codes[i]
		local lgrp = by_code[lc]
		for j = i, #main_pend_codes do
			local rc = main_pend_codes[j]
			local rgrp = by_code[rc]
			if i ~= j or #lgrp.entries >= 2 then
				local le = lgrp.entries[1]
				local re = (i == j) and rgrp.entries[2] or rgrp.entries[1]
				clear_board()
				helpers.place(le.card, 0, 0, LOCATION_SZONE, helpers.pzone_seq(0), POS_FACEUP_ATTACK, true, false)
				helpers.place(re.card, 0, 0, LOCATION_SZONE, helpers.pzone_seq(1), POS_FACEUP_ATTACK, true, false)
				local ls = le.card:GetLeftScale()
				local rs = re.card:GetRightScale()
				local pend_eff = nil
				for _, eff in ipairs(le.effects) do
					if eff.scope == "card" and eff.code == EFFECT_SPSUMMON_PROC_G and eff.condition then
						pend_eff = eff
						break
					end
				end
				if pend_eff then
					local function pick_unused_pend_copy(code)
						local need = 1
						if code == lc then need = need + 1 end
						if code == rc then need = need + 1 end
						return by_code[code].entries[need]
					end
					local hand_targets, extra_targets, extra_proper_targets = {}, {}, {}
					for _, mc in ipairs(main_monster_codes) do
						local cand = pick_unused_pend_copy(mc)
						if cand then
							helpers.place(cand.card, 0, 0, LOCATION_HAND, 0, POS_FACEDOWN, false, false)
							if safe_call(pend_eff.condition, pend_eff.effect, le.card, Group.FromCards(cand.card)) then
								hand_targets[#hand_targets + 1] = tostring(cand.copy)
							end
							helpers.remove(cand.card)
						end
					end
					-- Check Main Pendulums face-up in Extra & Extra/Pendulum composites
					local all_pend = {}
					for _, pc in ipairs(main_pend_codes) do all_pend[#all_pend + 1] = pc end
					for _, pc in ipairs(extra_pend_codes) do all_pend[#all_pend + 1] = pc end
					for _, pc in ipairs(all_pend) do
						local cand = pick_unused_pend_copy(pc)
						if cand then
							helpers.place(cand.card, 0, 0, LOCATION_EXTRA, 0, POS_FACEUP_DEFENSE, false, false)
							if safe_call(pend_eff.condition, pend_eff.effect, le.card, Group.FromCards(cand.card)) then
								extra_targets[#extra_targets + 1] = tostring(cand.copy)
							else
								helpers.remove(cand.card)
								helpers.place(cand.card, 0, 0, LOCATION_EXTRA, 0, POS_FACEUP_DEFENSE, false, true)
								if safe_call(pend_eff.condition, pend_eff.effect, le.card, Group.FromCards(cand.card)) then
									extra_proper_targets[#extra_proper_targets + 1] = tostring(cand.copy)
								end
							end
							helpers.remove(cand.card)
						end
					end
					if #hand_targets > 0 or #extra_targets > 0 or #extra_proper_targets > 0 then
						emit(string.format(
							"pendulum\t%d\t%d\t%d\t%d\t%s\t%s\t%s",
							le.copy, re.copy, ls, rs,
							#hand_targets > 0 and table.concat(hand_targets, ",") or "-",
							#extra_targets > 0 and table.concat(extra_targets, ",") or "-",
							#extra_proper_targets > 0 and table.concat(extra_proper_targets, ",") or "-"
						))
					end
				end
			end
		end
	end

	-- 5. Ritual Summon checks (branch-and-bound supporting >= 4 materials and truncated search status)
	if #ritual_reqs > 0 and #ritual_monster_codes > 0 then
		for _, req in ipairs(ritual_reqs) do
			local spell = stock_entries[req.copy]
			local eff = spell and spell.effects[req.ordinal + 1]
			if eff and eff.target then
				for _, rcode in ipairs(ritual_monster_codes) do
					local rgrp = by_code[rcode]
					local rentry = rgrp.entries[1]
					local target_lv = rentry.card:GetLevel()
					local r_items = {}
					local total_avail = 0
					clear_board()
					helpers.place(rentry.card, 0, 0, LOCATION_HAND, 0, POS_FACEDOWN, false, false)
					for _, mc in ipairs(all_monster_codes) do
						local mg = by_code[mc]
						local avail_start = (mc == rcode) and 2 or 1
						local avail = #mg.entries - avail_start + 1
						if avail > 0 then
							local c0 = mg.entries[1].card
							local base_lv = c0:GetLevel()
							local rlv = c0:GetRitualLevel(rentry.card)
							local lv1 = rlv & 0xffff
							local lv2 = rlv >> 16
							local lvs = {}
							if base_lv > 0 then lvs[#lvs + 1] = base_lv end
							if lv1 > 0 and lv1 ~= base_lv then lvs[#lvs + 1] = lv1 end
							if lv2 > 0 and lv2 ~= base_lv and lv2 ~= lv1 then lvs[#lvs + 1] = lv2 end
							if #lvs > 0 then
								local mn, mx = lvs[1], lvs[1]
								for i = 2, #lvs do
									if lvs[i] < mn then mn = lvs[i] end
									if lvs[i] > mx then mx = lvs[i] end
								end
								local prio = (mg.section == "extra" and 0 or (has_ss_proc[mc] and 1 or 2))
								r_items[#r_items + 1] = {
									code = mc, section = mg.section, entries = mg.entries,
									avail_start = avail_start, cap = avail,
									min_lv = mn, max_lv = mx, prio = prio,
								}
								total_avail = total_avail + avail
							end
						end
					end
					table.sort(r_items, function(a, b)
						if a.prio ~= b.prio then return a.prio < b.prio end
						if a.max_lv ~= b.max_lv then return a.max_lv > b.max_lv end
						return a.code < b.code
					end)
					local n_items = #r_items
					local rem_max_all = {}
					local max_lv_from = {}
					local min_lv_from = {}
					rem_max_all[n_items + 1] = 0
					max_lv_from[n_items + 1] = 0
					min_lv_from[n_items + 1] = 0
					for i = n_items, 1, -1 do
						rem_max_all[i] = rem_max_all[i + 1] + r_items[i].cap * r_items[i].max_lv
						max_lv_from[i] = (i == n_items) and r_items[i].max_lv or math.max(r_items[i].max_lv, max_lv_from[i + 1])
						min_lv_from[i] = (i == n_items) and r_items[i].min_lv or math.min(r_items[i].min_lv, min_lv_from[i + 1])
					end
					local accepted = 0
					local checks = 0
					local visits = 0
					local max_checks = 240
					local max_visits = 20000
					local truncated = false
					local max_mat_ct = math.min(total_avail, math.max(target_lv, 12))
					-- Test exact-level sums first, then minimal overpayment (>= target_lv)
					for pass_exact = 1, 2 do
						for mat_ct = 1, max_mat_ct do
							if accepted >= 24 or checks >= max_checks or visits >= max_visits then break end
							if target_lv > 0 and mat_ct * max_lv_from[1] < target_lv then
								-- impossible with mat_ct materials
							elseif pass_exact == 1 and target_lv > 0 and mat_ct * min_lv_from[1] > target_lv then
								-- impossible exact sum with mat_ct materials
							elseif rem_max_all[1] >= target_lv then
								local chosen_items = {}
								local chosen_counts = {}
								local stop_now = false
								local function test_leaf()
									local mat_actual = {}
									for i = 1, n_items do
										local cnt = chosen_counts[i] or 0
										if cnt > 0 then
											local it = r_items[i]
											for u = 1, cnt do
												mat_actual[#mat_actual + 1] = it.entries[it.avail_start + u - 1]
											end
										end
									end
									checks = checks + 1
									local ok = false
									for _, main_loc in ipairs({LOCATION_HAND, LOCATION_MZONE}) do
										clear_board()
										Duel.SetLP(0, 8000)
										helpers.place(spell.card, 0, 0, LOCATION_SZONE, 0, POS_FACEUP_ATTACK, false, false)
										helpers.place(rentry.card, 0, 0, LOCATION_HAND, 0, POS_FACEDOWN, false, false)
										local placed_all = true
										local mzone_seq = 0
										for _, act in ipairs(mat_actual) do
											if act.section == "extra" or main_loc == LOCATION_MZONE then
												if mzone_seq >= 5 then
													placed_all = false
													break
												end
												helpers.place(act.card, 0, 0, LOCATION_MZONE, mzone_seq, POS_FACEUP_ATTACK, false, true)
												mzone_seq = mzone_seq + 1
											else
												helpers.place(act.card, 0, 0, LOCATION_HAND, 0, POS_FACEDOWN, false, false)
											end
										end
										local cond_ok = (not eff.condition) or safe_call(eff.condition, eff.effect, 0, g0, 0, 0, nil, REASON_EFFECT, 0, 0)
										if placed_all and cond_ok and safe_call(eff.target, eff.effect, 0, g0, 0, 0, nil, REASON_EFFECT, 0, 0) then
											ok = true
											break
										end
									end
									if ok then
										accepted = accepted + 1
										emit(string.format("ritual\t%d\t%d\t%s", req.qi, rentry.copy, join_copies(mat_actual)))
									end
									if accepted >= 24 or checks >= max_checks then
										if checks >= max_checks and accepted < 24 then truncated = true end
										stop_now = true
									end
								end
								local function rec(idx, depth, cur_min, cur_max, cur_min_lv)
									if stop_now then return end
									visits = visits + 1
									if visits >= max_visits then
										truncated = true
										stop_now = true
										return
									end
									local k_rem = mat_ct - depth
									if k_rem == 0 then
										if pass_exact == 1 then
											if cur_max >= target_lv and cur_min <= target_lv then
												test_leaf()
											end
										else
											if cur_max >= target_lv and (cur_min - cur_min_lv) < target_lv then
												test_leaf()
											end
										end
										return
									end
									if idx > n_items then return end
									local upper_add = math.min(rem_max_all[idx], k_rem * max_lv_from[idx])
									if cur_max + upper_add < target_lv then return end
									local lower_add = k_rem * min_lv_from[idx]
									if pass_exact == 1 then
										if cur_min + lower_add > target_lv then return end
									else
										local over_lb = (depth == 0) and ((k_rem - 1) * min_lv_from[idx])
											or math.min(cur_min + (k_rem - 1) * min_lv_from[idx], (cur_min - cur_min_lv) + k_rem * min_lv_from[idx])
										if over_lb >= target_lv then return end
									end
									for i = idx, n_items do
										local it = r_items[i]
										local used = chosen_counts[i] or 0
										if used < it.cap then
											chosen_counts[i] = used + 1
											local next_min_lv = (depth == 0) and it.min_lv or math.min(cur_min_lv, it.min_lv)
											rec(i, depth + 1, cur_min + it.min_lv, cur_max + it.max_lv, next_min_lv)
											chosen_counts[i] = used
											if stop_now then return end
										end
									end
								end
								if n_items > 0 then
									rec(1, 0, 0, 0, 0)
								end
							end
						end
					end
					if accepted == 0 and truncated then
						emit(string.format("ritual_incomplete\t%d\t%d\tbudget_exhausted", req.qi, rentry.copy))
					end
				end
			end
		end
	end

	clear_board()
	return table.concat(out, "\n") .. (#out > 0 and "\n" or "")
end
