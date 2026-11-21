-- Execute the registered stock predicate with the original fusion procedure.
-- A card may satisfy a zone predicate in several ways, but its physical index
-- may occur only once in a selected group, including the Extra Deck recipient.
return function(target_check, effect, stock, recipient_indices, other_material_source)
	local group_check, fusion_check = Group.CheckSubGroup, Card.CheckFusionMaterial
	local current_recipient, selected, options = nil, nil, {}
	local material_choices = {}
	local checked, incomplete, external_query = false, false, false
	local indices, locations = {}, {}
	local handler = effect:GetHandler()
	for _, entry in ipairs(stock) do
		indices[entry[1]], locations[entry[1]] = entry[2], entry[3]
	end

	local function matches(filter, player, own, opponent, excluded, ...)
		if player ~= 0 or opponent ~= 0 then
			external_query = true
			return Group.CreateGroup()
		end
		local result = Group.CreateGroup()
		for _, entry in ipairs(stock) do
			local card, index, location = table.unpack(entry)
			if own & location ~= 0 and card ~= excluded
				and not (type(excluded) == 'userdata' and getmetatable(excluded) == Group and excluded:IsContains(card)) then
				if location == LOCATION_EXTRA then material_choices[card] = nil end
				if not filter or filter(card, ...) then
					result:AddCard(card)
					if material_choices[card] then options[index] = material_choices[card] end
				end
			end
		end
		return result
	end

	local function copies(group)
		local seen, total = {}, 0
		for card in aux.Next(group) do
			if not seen[indices[card]] then
				seen[indices[card]] = true
				total = total + 1
			end
		end
		return total
	end

	Duel.GetMatchingGroup = matches
	Duel.GetMatchingGroupCount = function(...)
		return copies(matches(...))
	end
	Duel.IsExistingMatchingCard = function(filter, player, own, opponent, count, excluded, ...)
		return copies(matches(filter, player, own, opponent, excluded, ...)) >= count
	end
	Duel.GetFusionMaterial = function(player, mask)
		local base = matches(Card.IsType, player, mask or LOCATION_HAND | LOCATION_MZONE, 0, nil, TYPE_MONSTER)
		return base:Clone(), base
	end
	Duel.GetChainMaterial = function()
		incomplete = incomplete or other_material_source
		return nil
	end

	Group.CheckSubGroup = function(group, goal, minimum, maximum, ...)
		if not current_recipient then
			return group_check(group, goal, minimum, maximum, ...)
		end
		return group_check(group, function(chosen, ...)
			local seen = {[indices[current_recipient]] = true}
			local assignment = {}
			for card in aux.Next(chosen) do
				local index = indices[card]
				if not index or seen[index] then return false end
				seen[index] = true
				assignment[#assignment + 1] = {index, locations[card]}
			end
			if not goal(chosen, ...) then return false end
			selected = assignment
			return true
		end, minimum, maximum, ...)
	end
	Card.CheckFusionMaterial = function(card, materials, required, ...)
		local index = indices[card]
		if not recipient_indices[index] or locations[card] ~= LOCATION_EXTRA or not card:IsType(TYPE_FUSION) then
			incomplete = true
			return false
		end
		checked = true
		current_recipient, selected = card, nil
		local found = fusion_check(card, materials, required, ...)
		current_recipient = nil
		if found and selected and (not required or indices[required]) then
			material_choices[card] = selected
		elseif found then
			-- A condition that does not disclose its assignment cannot reserve stock.
			incomplete = true
			return false
		end
		return found
	end

	local ready = target_check(effect, 0, Group.FromCards(handler), 0, 0, nil, REASON_EFFECT, 0, 0)
	if ready and not external_query and next(options) then return 'inventory_present', options end
	if ready or incomplete or external_query or not checked or next(options) then return 'unknown', {} end
	return 'missing', {}
end
