-- Delete all app data for users matching the given emails.
-- Covers: owner, tenant, manager, guest roles and related tables.
-- Run with: psql -v emails="'{\"user@example.com\"}'" -f delete_user_data.sql
-- Or inline: DO $$ ... END $$;

DO $$
DECLARE
  emails text[] := ARRAY[
    'walexes826@medevsa.com'
  ];
  user_ids int[];
  owner_profile_ids int[];
  property_ids int[];
  unit_ids int[];
  stay_ids int[];
  invitation_ids int[];
BEGIN
  SELECT array_agg(id) INTO user_ids FROM users WHERE email = ANY(emails);
  IF user_ids IS NULL THEN user_ids := ARRAY[]::int[]; END IF;

  SELECT array_agg(id) INTO owner_profile_ids FROM owner_profiles WHERE user_id = ANY(user_ids);
  IF owner_profile_ids IS NULL THEN owner_profile_ids := ARRAY[]::int[]; END IF;

  SELECT array_agg(id) INTO property_ids FROM properties WHERE owner_profile_id = ANY(owner_profile_ids);
  IF property_ids IS NULL THEN property_ids := ARRAY[]::int[]; END IF;

  SELECT array_agg(id) INTO unit_ids FROM units WHERE property_id = ANY(property_ids);
  IF unit_ids IS NULL THEN unit_ids := ARRAY[]::int[]; END IF;

  SELECT array_agg(id) INTO stay_ids FROM stays
    WHERE guest_id = ANY(user_ids) OR owner_id = ANY(user_ids) OR property_id = ANY(property_ids);
  IF stay_ids IS NULL THEN stay_ids := ARRAY[]::int[]; END IF;

  SELECT array_agg(id) INTO invitation_ids FROM invitations
    WHERE owner_id = ANY(user_ids) OR invited_by_user_id = ANY(user_ids) OR property_id = ANY(property_ids);
  IF invitation_ids IS NULL THEN invitation_ids := ARRAY[]::int[]; END IF;

  -- Event ledger & audit logs (if exists)
  DELETE FROM event_ledger
  WHERE actor_user_id = ANY(user_ids) OR property_id = ANY(property_ids)
     OR unit_id = ANY(unit_ids) OR stay_id = ANY(stay_ids) OR invitation_id = ANY(invitation_ids);

  DELETE FROM audit_logs
  WHERE actor_user_id = ANY(user_ids) OR property_id = ANY(property_ids)
     OR stay_id = ANY(stay_ids) OR invitation_id = ANY(invitation_ids);

  -- Presence (away periods, stay presence, resident presence)
  DELETE FROM presence_away_periods
  WHERE stay_id = ANY(stay_ids)
     OR resident_presence_id IN (SELECT id FROM resident_presences WHERE user_id = ANY(user_ids) OR unit_id = ANY(unit_ids));

  DELETE FROM stay_presences WHERE stay_id = ANY(stay_ids);

  DELETE FROM resident_presences WHERE user_id = ANY(user_ids) OR unit_id = ANY(unit_ids);

  -- Resident mode (owner/manager personal mode)
  DELETE FROM resident_modes WHERE user_id = ANY(user_ids) OR unit_id = ANY(unit_ids);

  -- Tenant & manager assignments
  DELETE FROM tenant_assignments WHERE user_id = ANY(user_ids) OR unit_id = ANY(unit_ids);

  DELETE FROM property_manager_assignments WHERE user_id = ANY(user_ids) OR property_id = ANY(property_ids);

  DELETE FROM manager_invitations WHERE invited_by_user_id = ANY(user_ids) OR property_id = ANY(property_ids);

  -- Guest pending invites
  DELETE FROM guest_pending_invites WHERE user_id = ANY(user_ids) OR invitation_id = ANY(invitation_ids);

  -- Invitations
  DELETE FROM invitations
  WHERE owner_id = ANY(user_ids) OR invited_by_user_id = ANY(user_ids) OR property_id = ANY(property_ids);

  -- Agreements & signatures
  DELETE FROM agreement_signatures WHERE used_by_user_id = ANY(user_ids);

  DELETE FROM property_authority_letters WHERE property_id = ANY(property_ids);

  DELETE FROM property_utility_providers WHERE property_id = ANY(property_ids);

  -- Stays
  DELETE FROM stays
  WHERE guest_id = ANY(user_ids) OR owner_id = ANY(user_ids) OR property_id = ANY(property_ids);

  -- Units
  DELETE FROM units WHERE property_id = ANY(property_ids);

  -- Properties
  DELETE FROM properties WHERE owner_profile_id = ANY(owner_profile_ids);

  DELETE FROM owner_poa_signatures WHERE used_by_user_id = ANY(user_ids);

  -- Profiles
  DELETE FROM owner_profiles WHERE user_id = ANY(user_ids);

  DELETE FROM guest_profiles WHERE user_id = ANY(user_ids);

  -- Pending registrations
  DELETE FROM pending_registrations WHERE email = ANY(emails);

  -- Users
  DELETE FROM users WHERE email = ANY(emails);

  RAISE NOTICE 'Deleted all data for % users with the given emails.', COALESCE(array_length(user_ids, 1), 0);
END $$;
