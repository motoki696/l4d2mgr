#pragma semicolon 1
#pragma newdecls required
#include <sourcemod>
#include <geoip>

public Plugin myinfo =
{
    name = "L4D2 Manager: Country Filter",
    author = "motoki",
    description = "Reject connections from blocked country codes",
    version = "0.1.0",
    url = ""
};

ConVar g_cv_enable;
Database g_db;
StringMap g_blocklist;
bool g_connecting;
char g_logPath[PLATFORM_MAX_PATH];

public void OnPluginStart()
{
    g_cv_enable = CreateConVar("l4d2mgr_country_filter_enable", "1", "Enable country filter", FCVAR_NONE, true, 0.0, true, 1.0);
    AutoExecConfig(true, "l4d2mgr_country_filter");
    BuildPath(Path_SM, g_logPath, sizeof(g_logPath), "logs/l4d2mgr_country_filter.log");
    RegAdminCmd("sm_l4d2cf_reload", Cmd_ReloadCountryFilter, ADMFLAG_CONFIG, "Reload country filter blocklist");
    RegAdminCmd("sm_l4d2cf_testip", Cmd_TestIp, ADMFLAG_CONFIG, "Test GeoIP lookup for an IP address (does not require a live connection)");
    CreateTimer(60.0, TimerReload, _, TIMER_REPEAT | TIMER_FLAG_NO_MAPCHANGE);
}

public void OnConfigsExecuted() { LoadBlocklist(); }

void LoadBlocklist()
{
    if (g_db != null) { g_db.Query(OnQueryResult, "SELECT country_code FROM country_filter_blocklist"); return; }
    if (g_connecting) return;
    g_connecting = true;
    Database.Connect(OnDbConnect, "l4d2mgr");
}

public void OnDbConnect(Database db, const char[] error, any data)
{
    g_connecting = false;
    if (db == null) { LogError("CountryFilter: DB connect failed: %s", error); return; }
    g_db = db;
    g_db.Query(OnQueryResult, "SELECT country_code FROM country_filter_blocklist");
}

public void OnQueryResult(Database db, DBResultSet results, const char[] error, any data)
{
    if (results == null) { LogError("CountryFilter: DB query failed: %s", error); return; }
    StringMap newMap = new StringMap();
    char code[3]; int count;
    while (results.FetchRow())
    {
        results.FetchString(0, code, sizeof(code));
        if (code[0] != '\0') { newMap.SetValue(code, true); count++; }
    }
    if (g_blocklist != null) { delete g_blocklist; }
    g_blocklist = newMap;
    LogMessage("[CountryFilter] Loaded %d blocklist entries", count);
}

public Action TimerReload(Handle timer) { LoadBlocklist(); return Plugin_Continue; }

public Action Cmd_ReloadCountryFilter(int client, int args)
{
    ReplyToCommand(client, "[CountryFilter] Reloading...");
    LoadBlocklist();
    return Plugin_Handled;
}

public Action Cmd_TestIp(int client, int args)
{
    if (args < 1) { ReplyToCommand(client, "Usage: sm_l4d2cf_testip <ip>"); return Plugin_Handled; }
    char ip[64];
    GetCmdArg(1, ip, sizeof(ip));
    char code[3];
    if (GeoipCode2(ip, code))
    {
        bool blocked;
        bool isBlocked = (g_blocklist != null && g_blocklist.GetValue(code, blocked) && blocked);
        ReplyToCommand(client, "[CountryFilter] %s -> %s (blocked=%s)", ip, code, isBlocked ? "yes" : "no");
    }
    else
    {
        ReplyToCommand(client, "[CountryFilter] %s -> lookup failed (private/unknown IP)", ip);
    }
    return Plugin_Handled;
}

public bool OnClientConnect(int client, char[] rejectmsg, int maxlen)
{
    if (!g_cv_enable.BoolValue || g_blocklist == null || IsFakeClient(client)) { return true; }
    char ip[64];
    GetClientIP(client, ip, sizeof(ip));
    char code[3];
    if (!GeoipCode2(ip, code)) { return true; }
    bool blocked;
    if (!g_blocklist.GetValue(code, blocked) || !blocked) { return true; }
    FormatEx(rejectmsg, maxlen, "Connection rejected: Country %s is blocked.", code);
    char steamid[64];
    GetClientAuthId(client, AuthId_Steam2, steamid, sizeof(steamid));
    LogToFileEx(g_logPath, "Blocked: IP=%s Country=%s SteamID=%s", ip, code, steamid);
    return false;
}
