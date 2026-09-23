#pragma semicolon 1
#pragma newdecls required

#include <sourcemod>

public Plugin myinfo =
{
    name = "L4D2 Manager: Mode Lock",
    author = "motoki",
    description = "Reject and reset disallowed game modes (lobby reservation)",
    version = "0.1.0",
    url = ""
};

ConVar g_cv_enable;
ConVar g_cv_allowed;
ConVar g_cv_map;

bool g_wrongMode;
bool g_resetIssued;
char g_badMode[64];
char g_logPath[PLATFORM_MAX_PATH];

public void OnPluginStart()
{
    g_cv_enable = CreateConVar("l4d2mgr_modelock_enable", "1", "Enable mode lock", FCVAR_NONE, true, 0.0, true, 1.0);
    g_cv_allowed = CreateConVar("l4d2mgr_modelock_allowed", "coop", "Comma separated list of allowed mp_gamemode values", FCVAR_NONE);
    g_cv_map = CreateConVar("l4d2mgr_modelock_map", "c1m1_hotel", "Map loaded when resetting", FCVAR_NONE);

    AutoExecConfig(true, "l4d2mgr_modelock");

    BuildPath(Path_SM, g_logPath, sizeof(g_logPath), "logs/l4d2mgr_modelock.log");
}

bool IsModeAllowed(const char[] mode, char[] firstAllowed, int firstLen)
{
    char allowed[512];
    g_cv_allowed.GetString(allowed, sizeof(allowed));

    char parts[16][64];
    int count = ExplodeString(allowed, ",", parts, sizeof(parts), sizeof(parts[]));
    firstAllowed[0] = '\0';
    bool foundMatch = false;

    for (int i = 0; i < count; i++)
    {
        TrimString(parts[i]);
        if (parts[i][0] == '\0')
        {
            continue;
        }

        if (firstAllowed[0] == '\0')
        {
            strcopy(firstAllowed, firstLen, parts[i]);
        }

        if (mode[0] != '\0' && strcmp(parts[i], mode, false) == 0)
        {
            foundMatch = true;
        }
    }

    if (firstAllowed[0] == '\0')
    {
        strcopy(firstAllowed, firstLen, "coop");
        if (mode[0] == '\0')
        {
            return true;
        }
        return strcmp(mode, "coop", false) == 0;
    }

    if (mode[0] == '\0')
    {
        return true;
    }

    return foundMatch;
}

void IssueReset()
{
    if (g_resetIssued)
    {
        return;
    }
    g_resetIssued = true;

    char firstAllowed[64];
    IsModeAllowed("", firstAllowed, sizeof(firstAllowed));

    ConVar mp_gamemode = FindConVar("mp_gamemode");
    if (mp_gamemode != null)
    {
        mp_gamemode.SetString(firstAllowed);
    }

    char map[64];
    g_cv_map.GetString(map, sizeof(map));
    if (!IsMapValid(map))
    {
        LogToFileEx(g_logPath, "Invalid reset map '%s'; using default c1m1_hotel", map);
        strcopy(map, sizeof(map), "c1m1_hotel");
    }

    LogToFileEx(g_logPath, "Reset: mp_gamemode=%s changelevel %s", firstAllowed, map);
    ServerCommand("changelevel %s", map);
}

public void OnMapStart()
{
    g_wrongMode = false;
    g_resetIssued = false;

    if (!g_cv_enable.BoolValue)
    {
        return;
    }

    ConVar mp_gamemode = FindConVar("mp_gamemode");
    if (mp_gamemode == null)
    {
        return;
    }

    mp_gamemode.GetString(g_badMode, sizeof(g_badMode));

    char first[64];
    if (!IsModeAllowed(g_badMode, first, sizeof(first)))
    {
        g_wrongMode = true;
        LogToFileEx(g_logPath, "Disallowed mp_gamemode '%s' at map start; resetting", g_badMode);
        CreateTimer(1.0, Timer_Reset, _, TIMER_FLAG_NO_MAPCHANGE);
    }
}

public Action Timer_Reset(Handle timer)
{
    if (g_wrongMode)
    {
        IssueReset();
    }
    return Plugin_Stop;
}

public bool OnClientConnect(int client, char[] rejectmsg, int maxlen)
{
    if (g_wrongMode && !IsFakeClient(client))
    {
        char allowed[512];
        g_cv_allowed.GetString(allowed, sizeof(allowed));
        FormatEx(rejectmsg, maxlen, "This server only allows game mode: %s", allowed);
        LogToFileEx(g_logPath, "Rejected connection (mode '%s')", g_badMode);
        IssueReset();
        return false;
    }
    return true;
}
