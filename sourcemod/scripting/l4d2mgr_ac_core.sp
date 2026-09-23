#pragma semicolon 1
#pragma newdecls required

#include <sourcemod>

public Plugin myinfo =
{
    name = "L4D2 Manager: AC Core",
    author = "motoki",
    description = "Detection recording core (no auto-ban)",
    version = "0.1.0",
    url = ""
};

Database g_db;
bool g_connecting;
StringMap g_lastReport;
char g_logPath[PLATFORM_MAX_PATH];
ConVar g_cvar_server_id;
ConVar g_cvar_cooldown;

public APLRes AskPluginLoad2(Handle myself, bool late, char[] error, int err_max)
{
    CreateNative("L4D2AC_Report", Native_Report);
    RegPluginLibrary("l4d2mgr_ac");
    return APLRes_Success;
}

public void OnPluginStart()
{
    g_cvar_server_id = CreateConVar("l4d2mgr_ac_server_id", "1", "Server ID", FCVAR_NONE, true, 1.0);
    g_cvar_cooldown = CreateConVar("l4d2mgr_ac_cooldown", "60.0", "Cooldown between reports per client+detector", FCVAR_NONE, true, 5.0, true, 3600.0);
    AutoExecConfig(true, "l4d2mgr_ac_core");

    g_lastReport = new StringMap();

    BuildPath(Path_SM, g_logPath, sizeof(g_logPath), "logs/l4d2mgr_ac.log");

    Connect();
}

public void OnMapStart()
{
    g_lastReport.Clear();
}

void Connect()
{
    if (g_db != null || g_connecting)
    {
        return;
    }
    g_connecting = true;
    Database.Connect(OnDbConnected, "l4d2mgr");
}

public void OnDbConnected(Database db, const char[] error, any data)
{
    g_connecting = false;
    if (db == null)
    {
        LogError("[L4D2AC] DB connect failed: %s", error);
        CreateTimer(30.0, Timer_Reconnect, _, TIMER_FLAG_NO_MAPCHANGE);
        return;
    }
    g_db = db;
    g_db.SetCharset("utf8mb4");
}

public Action Timer_Reconnect(Handle timer)
{
    Connect();
    return Plugin_Stop;
}

public any Native_Report(Handle plugin, int numParams)
{
    int client = GetNativeCell(1);
    char detector[33];
    GetNativeString(2, detector, sizeof(detector));
    int severity = GetNativeCell(3);
    char detail[256];
    GetNativeString(4, detail, sizeof(detail));

    // Validate client
    if (client <= 0 || client > MaxClients || !IsClientInGame(client) || IsFakeClient(client))
    {
        return false;
    }

    // Validate severity
    if (severity < 1 || severity > 3)
    {
        return false;
    }

    // Validate detector string
    int detLen = strlen(detector);
    if (detLen < 1 || detLen > 32)
    {
        return false;
    }
    for (int i = 0; i < detLen; i++)
    {
        char c = detector[i];
        if (!((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '_'))
        {
            return false;
        }
    }

    // Cooldown
    char key[64];
    Format(key, sizeof(key), "%d:%s", GetClientUserId(client), detector);
    float lastTime;
    float now = GetEngineTime();
    if (g_lastReport.GetValue(key, lastTime))
    {
        float cooldown = g_cvar_cooldown.FloatValue;
        if (now - lastTime < cooldown)
        {
            return false;
        }
    }
    g_lastReport.SetValue(key, now);

    // Gather data
    char steam2[32];
    bool hasSteam2 = GetClientAuthId(client, AuthId_Steam2, steam2, sizeof(steam2));
    if (!hasSteam2)
    {
        strcopy(steam2, sizeof(steam2), "STEAM_ID_PENDING");
    }

    char steamid64[32];
    bool hasSteam64 = GetClientAuthId(client, AuthId_SteamID64, steamid64, sizeof(steamid64));
    if (!hasSteam64)
    {
        strcopy(steamid64, sizeof(steamid64), "0");
    }

    char name[64];
    GetClientName(client, name, sizeof(name));

    char map[64];
    GetCurrentMap(map, sizeof(map));

    // Log to file
    LogToFileEx(g_logPath, "[%s] sev=%d %N <%s> map=%s : %s", detector, severity, client, steam2, map, detail);

    // Notify admins
    for (int i = 1; i <= MaxClients; i++)
    {
        if (!IsClientInGame(i) || IsFakeClient(i))
        {
            continue;
        }
        if (!CheckCommandAccess(i, "sm_l4d2ac_notify", ADMFLAG_BAN))
        {
            continue;
        }
        PrintToChat(i, "\x04[AC]\x01 %N: %s (sev %d) - %s", client, detector, severity, detail);
    }

    // Insert into database
    if (g_db != null)
    {
        int serverId = g_cvar_server_id.IntValue;

        char escapedSteam2[512];
        char escapedSteamID64[512];
        char escapedName[512];
        char escapedMap[512];
        char escapedDetector[512];
        char escapedDetail[512];

        g_db.Escape(steam2, escapedSteam2, sizeof(escapedSteam2));
        g_db.Escape(steamid64, escapedSteamID64, sizeof(escapedSteamID64));
        g_db.Escape(name, escapedName, sizeof(escapedName));
        g_db.Escape(map, escapedMap, sizeof(escapedMap));
        g_db.Escape(detector, escapedDetector, sizeof(escapedDetector));
        g_db.Escape(detail, escapedDetail, sizeof(escapedDetail));

        char query[2048];
        Format(query, sizeof(query),
            "INSERT INTO detections (server_id, detector, severity, steamid, steamid64, name, map, detail) VALUES (%d, '%s', %d, '%s', '%s', '%s', '%s', '%s')",
            serverId, escapedDetector, severity, escapedSteam2, escapedSteamID64, escapedName, escapedMap, escapedDetail);

        g_db.Query(OnInsertDone, query);
    }
    else
    {
        LogError("[L4D2AC] DB not connected; attempting reconnect.");
        Connect();
    }

    return true;
}

public void OnInsertDone(Database db, DBResultSet results, const char[] error, any data)
{
    if (results == null)
    {
        LogError("[L4D2AC] insert failed: %s", error);
    }
}
