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

	local function assignment(group)
		local seen = {[indices[current_recipient]] = true}
		local items = {}
		for card in aux.Next(group) do
			local index = indices[card]
			if not index or seen[index] then return nil end
			seen[index] = true
			items[#items + 1] = {index, locations[card]}
		end
		return items
	end

	Group.CheckSubGroup = function(group, goal, minimum, maximum, ...)
		if not current_recipient then
			return group_check(group, goal, minimum, maximum, ...)
		end
		return group_check(group, function(chosen, ...)
			local items = assignment(chosen)
			if not items or not goal(chosen, ...) then return false end
			selected = items
			return true
		end, minimum, maximum, ...)
	end

	local function confirmed_group(card, materials, required, ...)
		-- Some native procedures return only a Boolean. Confirm a distinct
		-- set with the same predicate and remove stock it can dispense with.
		if not materials then return nil end
		local target = indices[card]
		for _, preferred in ipairs({LOCATION_HAND, LOCATION_MZONE, LOCATION_GRAVE, LOCATION_DECK, LOCATION_REMOVED}) do
			local by_copy = {}
			for member in aux.Next(materials) do
				local copy = indices[member]
				if copy and copy ~= target and (not required or by_copy[copy] ~= required)
					and (not by_copy[copy] or member == required or locations[member] == preferred) then
					by_copy[copy] = member
				end
			end
			local group = Group.CreateGroup()
			for _, member in pairs(by_copy) do group:AddCard(member) end
			if #group > 0 and (not required or group:IsContains(required)) and fusion_check(card, group, required, ...) then
				for copy = 1, #stock do
					local member = by_copy[copy]
					if member and member ~= required then
						group:RemoveCard(member)
						if #group == 0 or not fusion_check(card, group, required, ...) then group:AddCard(member) end
					end
				end
				return assignment(group)
			end
		end
		return nil
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
		if found and not selected then selected = confirmed_group(card, materials, required, ...) end
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
