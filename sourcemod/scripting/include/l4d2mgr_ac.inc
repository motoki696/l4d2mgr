#if defined _l4d2mgr_ac_included
 #endinput
#endif
#define _l4d2mgr_ac_included

/**
 * Report a detection to l4d2mgr_ac_core (detection only; never bans).
 *
 * @param client     Client index (must be in-game, not a bot).
 * @param detector   Detector id, [a-z0-9_]{1,32} (e.g. "speedhack").
 * @param severity   1 = low, 2 = medium, 3 = high.
 * @param detail     Free text evidence, max 255 bytes.
 * @return           true if recorded, false if rejected (invalid args or in cooldown).
 */
native bool L4D2AC_Report(int client, const char[] detector, int severity, const char[] detail);

public SharedPlugin __pl_l4d2mgr_ac =
{
	name = "l4d2mgr_ac",
	file = "l4d2mgr_ac_core.smx",
#if defined REQUIRE_PLUGIN
	required = 1,
#else
	required = 0,
#endif
};

#if !defined REQUIRE_PLUGIN
public void __pl_l4d2mgr_ac_SetNTVOptional()
{
	MarkNativeAsOptional("L4D2AC_Report");
}
#endif
