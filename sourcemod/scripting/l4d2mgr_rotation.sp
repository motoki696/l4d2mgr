#pragma semicolon 1
#pragma newdecls required
#include <sourcemod>

static const char g_defaultMaps[][] =
{
    "c1m1_hotel",
    "c2m1_highway",
    "c3m1_plankcountry",
    "c4m1_milltown_a",
    "c5m1_waterfront",
    "c6m1_riverbank",
    "c7m1_docks",
    "c8m1_apartment",
    "c9m1_alleys",
    "c10m1_caves",
    "c11m1_greenhouse",
    "c12m1_hilltop",
    "c13m1_alpinecreek",
    "c14m1_junkyard"
};

Database g_db;
ArrayList g_rotation;
ConVar g_cvarEnable;
ConVar g_cvarDelay;
ConVar g_cvarMode;
ConVar g_cvarServerId;
char g_nextMap[64];
bool g_changePending;
bool g_connecting;
char g_source[16];

public Plugin myinfo =
{
    name = "L4D2 Manager: Campaign Rotation",
    author = "motoki",
    description = "Campaign rotation driven by l4d2mgr DB",
    version = "0.1.0",
    url = ""
};

public void OnPluginStart()
{
    g_cvarEnable = CreateConVar("l4d2mgr_rotation_enable", "1", "Enable rotation", 0, true, 0.0, true, 1.0);
    g_cvarDelay = CreateConVar("l4d2mgr_rotation_delay", "15.0", "Delay seconds after finale win", 0, true, 3.0, true, 120.0);
    g_cvarMode = CreateConVar("l4d2mgr_rotation_mode", "0", "0=sequential 1=random", 0, true, 0.0, true, 1.0);
    g_cvarServerId = CreateConVar("l4d2mgr_rotation_server_id", "1", "Server ID for DB lookup", 0, true, 1.0);

    AutoExecConfig(true, "l4d2mgr_rotation");

    g_rotation = new ArrayList(ByteCountToCells(64));

    RegAdminCmd("sm_rotation", Cmd_Rotation, ADMFLAG_GENERIC, "Show rotation list");
    RegAdminCmd("sm_rotation_reload", Cmd_RotationReload, ADMFLAG_CONFIG, "Reload rotation");
    RegAdminCmd("sm_rotation_next", Cmd_RotationNext, ADMFLAG_CHANGEMAP, "Force next map now");

    HookEvent("finale_win", Event_FinaleWin, EventHookMode_PostNoCopy);
}

public void OnConfigsExecuted()
{
    LoadRotation();
}

void LoadRotation()
{
    if (g_db != null)
    {
        char query[256];
        Format(query, sizeof(query), "SELECT map FROM rotation WHERE server_id = %d AND enabled = 1 ORDER BY position ASC", g_cvarServerId.IntValue);
        g_db.Query(OnQueryResult, query);
        return;
    }

    if (g_connecting)
        return;

    g_connecting = true;
    Database.Connect(OnDbConnect, "l4d2mgr");
}

public void OnDbConnect(Database db, const char[] error, any data)
{
    g_connecting = false;

    if (db == null)
    {
        LogError("L4D2Mgr: DB connect failed: %s", error);
        LoadFromFile();
        return;
    }

    g_db = db;
    char query[256];
    Format(query, sizeof(query), "SELECT map FROM rotation WHERE server_id = %d AND enabled = 1 ORDER BY position ASC", g_cvarServerId.IntValue);
    g_db.Query(OnQueryResult, query);
}

public void OnQueryResult(Database db, DBResultSet results, const char[] error, any data)
{
    if (results == null)
    {
        LogError("L4D2Mgr: DB query failed: %s", error);
        LoadFromFile();
        return;
    }

    ArrayList temp = new ArrayList(ByteCountToCells(64));
    char map[64];
    while (results.FetchRow())
    {
        results.FetchString(0, map, sizeof(map));
        if (IsMapValid(map))
        {
            temp.PushString(map);
        }
        else
        {
            LogError("L4D2Mgr: Invalid map in DB: %s", map);
        }
    }

    int size = temp.Length;
    if (size >= 1)
    {
        g_rotation.Clear();
        for (int i = 0; i < size; i++)
        {
            char m[64];
            temp.GetString(i, m, sizeof(m));
            g_rotation.PushString(m);
        }
        strcopy(g_source, sizeof(g_source), "db");
        SaveToFile();
        LogMessage("[Rotation] source=db count=%d", size);
    }
    else
    {
        LoadFromFile();
    }

    delete temp;
}

void SaveToFile()
{
    char path[PLATFORM_MAX_PATH];
    BuildPath(Path_SM, path, sizeof(path), "data/l4d2mgr_rotation.txt");

    File file = OpenFile(path, "w");
    if (file == null)
    {
        LogError("L4D2Mgr: Cannot open %s for writing", path);
        return;
    }

    int size = g_rotation.Length;
    for (int i = 0; i < size; i++)
    {
        char map[64];
        g_rotation.GetString(i, map, sizeof(map));
        file.WriteLine("%s", map);
    }

    delete file;
}

void LoadFromFile()
{
    char path[PLATFORM_MAX_PATH];
    BuildPath(Path_SM, path, sizeof(path), "data/l4d2mgr_rotation.txt");

    File file = OpenFile(path, "r");
    if (file == null)
    {
        LoadDefaults();
        return;
    }

    ArrayList temp = new ArrayList(ByteCountToCells(64));
    char line[64];
    while (file.ReadLine(line, sizeof(line)))
    {
        TrimString(line);
        if (line[0] == '\0')
            continue;
        if (line[0] == '/' && line[1] == '/')
            continue;
        if (IsMapValid(line))
        {
            temp.PushString(line);
        }
        else
        {
            LogError("L4D2Mgr: Invalid map in file: %s", line);
        }
    }

    delete file;

    int size = temp.Length;
    if (size >= 1)
    {
        g_rotation.Clear();
        for (int i = 0; i < size; i++)
        {
            char m[64];
            temp.GetString(i, m, sizeof(m));
            g_rotation.PushString(m);
        }
        strcopy(g_source, sizeof(g_source), "file");
        LogMessage("[Rotation] source=file count=%d", size);
    }
    else
    {
        LoadDefaults();
    }

    delete temp;
}

void LoadDefaults()
{
    g_rotation.Clear();
    int count = sizeof(g_defaultMaps);
    for (int i = 0; i < count; i++)
    {
        g_rotation.PushString(g_defaultMaps[i]);
    }
    strcopy(g_source, sizeof(g_source), "default");
    LogMessage("[Rotation] source=default count=%d", count);
}

bool GetCampaignPrefix(const char[] map, char[] out, int maxlen)
{
    if (map[0] != 'c')
        return false;

    int i = 1;
    while (map[i] >= '0' && map[i] <= '9')
        i++;

    if (i == 1 || map[i] != 'm')
        return false;

    int len = i;
    if (len >= maxlen)
        len = maxlen - 1;

    for (int j = 0; j < len; j++)
        out[j] = map[j];
    out[len] = '\0';

    return true;
}

bool ChooseNextMap()
{
    g_nextMap[0] = '\0';

    int size = g_rotation.Length;
    if (size == 0)
    {
        LogError("L4D2Mgr: Rotation list is empty.");
        return false;
    }

    char current[64];
    GetCurrentMap(current, sizeof(current));

    char currentPrefix[16];
    bool hasPrefix = GetCampaignPrefix(current, currentPrefix, sizeof(currentPrefix));

    int index;
    if (g_cvarMode.IntValue == 0)
    {
        int idx = -1;
        for (int i = 0; i < size; i++)
        {
            char map[64];
            g_rotation.GetString(i, map, sizeof(map));
            char prefix[16];
            if (hasPrefix && GetCampaignPrefix(map, prefix, sizeof(prefix)) && StrEqual(prefix, currentPrefix))
            {
                idx = i;
                break;
            }
        }
        if (idx == -1)
            index = 0;
        else
            index = (idx + 1) % size;
    }
    else
    {
        index = GetRandomInt(0, size - 1);
        if (size >= 2 && hasPrefix)
        {
            for (int attempts = 0; attempts < 32; attempts++)
            {
                char map[64];
                g_rotation.GetString(index, map, sizeof(map));
                char prefix[16];
                if (!GetCampaignPrefix(map, prefix, sizeof(prefix)) || !StrEqual(prefix, currentPrefix))
                    break;
                index = GetRandomInt(0, size - 1);
            }
        }
    }

    g_rotation.GetString(index, g_nextMap, sizeof(g_nextMap));
    return true;
}

public void Event_FinaleWin(Event event, const char[] name, bool dontBroadcast)
{
    if (!g_cvarEnable.BoolValue || g_changePending)
        return;

    if (ChooseNextMap())
    {
        g_changePending = true;
        float delay = g_cvarDelay.FloatValue;
        PrintToChatAll("[Rotation] Next campaign: %s in %d seconds", g_nextMap, RoundToNearest(delay));
        CreateTimer(delay, Timer_ChangeLevel, _, TIMER_FLAG_NO_MAPCHANGE);
    }
}

public Action Timer_ChangeLevel(Handle timer)
{
    if (g_nextMap[0] != '\0' && IsMapValid(g_nextMap))
    {
        ForceChangeLevel(g_nextMap, "l4d2mgr rotation");
    }
    else
    {
        LogError("L4D2Mgr: Cannot change level, invalid map: %s", g_nextMap);
        g_changePending = false;
    }
    return Plugin_Stop;
}

public void OnMapStart()
{
    g_changePending = false;
}

public Action Cmd_Rotation(int client, int args)
{
    char modeStr[16];
    if (g_cvarMode.IntValue == 0)
        strcopy(modeStr, sizeof(modeStr), "sequential");
    else
        strcopy(modeStr, sizeof(modeStr), "random");

    ReplyToCommand(client, "[Rotation] source=%s mode=%s count=%d", g_source, modeStr, g_rotation.Length);

    char current[64];
    GetCurrentMap(current, sizeof(current));
    char currentPrefix[16];
    bool hasCurrent = GetCampaignPrefix(current, currentPrefix, sizeof(currentPrefix));

    int size = g_rotation.Length;
    for (int i = 0; i < size; i++)
    {
        char map[64];
        g_rotation.GetString(i, map, sizeof(map));

        bool isCurrent = false;
        if (hasCurrent)
        {
            char prefix[16];
            if (GetCampaignPrefix(map, prefix, sizeof(prefix)) && StrEqual(prefix, currentPrefix))
                isCurrent = true;
        }

        if (isCurrent)
            ReplyToCommand(client, "%2d. %s <- current", i + 1, map);
        else
            ReplyToCommand(client, "%2d. %s", i + 1, map);
    }

    return Plugin_Handled;
}

public Action Cmd_RotationReload(int client, int args)
{
    ReplyToCommand(client, "[Rotation] Reloading...");
    LoadRotation();
    return Plugin_Handled;
}

public Action Cmd_RotationNext(int client, int args)
{
    if (ChooseNextMap() && IsMapValid(g_nextMap))
    {
        ReplyToCommand(client, "Forcing changelevel to %s", g_nextMap);
        ForceChangeLevel(g_nextMap, "l4d2mgr rotation");
    }
    else
    {
        ReplyToCommand(client, "Failed to select next map.");
    }
    return Plugin_Handled;
}
