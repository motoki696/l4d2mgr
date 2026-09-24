#pragma semicolon 1
#pragma newdecls required

#include <sourcemod>
#include <geoip>

#define LOG_FILE "logs/l4d2mgr_country_filter.log"
#define DB_CONFIG "l4d2mgr_game"
#define REFRESH_INTERVAL 60.0

Database g_hDB = null;
StringMap g_hBlocklist = null;
ConVar g_hCvarEnabled;
bool g_bEnabled = true;
Handle g_hTimerRefresh = null;

public Plugin myinfo =
{
	name        = "l4d2mgr_country_filter",
	author      = "l4d2mgr",
	description = "Rejects connecting clients from blocklisted countries (GeoIP)",
	version     = "1.0.0",
	url         = ""
};

public void OnPluginStart()
{
	g_hCvarEnabled = CreateConVar("l4d2mgr_country_filter_enabled", "1",
		"Enable/disable the country filter", FCVAR_NONE, true, 0.0, true, 1.0);
	HookConVarChange(g_hCvarEnabled, OnCvarEnabledChanged);
	g_bEnabled = g_hCvarEnabled.BoolValue;

	RegAdminCmd("sm_l4d2cf_reload", Command_Reload, ADMFLAG_ROOT,
		"Reloads the country filter blocklist from the database");

	ConnectDatabase();
}

public void OnPluginEnd()
{
	if (g_hTimerRefresh != null)
	{
		KillTimer(g_hTimerRefresh);
		g_hTimerRefresh = null;
	}
	if (g_hBlocklist != null)
	{
		delete g_hBlocklist;
		g_hBlocklist = null;
	}
	if (g_hDB != null)
	{
		delete g_hDB;
		g_hDB = null;
	}
}

public void OnCvarEnabledChanged(ConVar convar, const char[] oldValue, const char[] newValue)
{
	g_bEnabled = convar.BoolValue;
}

public Action Command_Reload(int client, int args)
{
	RefreshBlocklist();
	ReplyToCommand(client, "[l4d2mgr] Country filter blocklist reload triggered.");
	return Plugin_Handled;
}

// --- DB接続 -------------------------------------------------

void ConnectDatabase()
{
	if (!SQL_CheckConfig(DB_CONFIG))
	{
		LogError("[l4d2mgr_country_filter] databases.cfg has no '%s' entry", DB_CONFIG);
		return;
	}

	Database.Connect(OnDBConnect, DB_CONFIG);
}

void OnDBConnect(Database db, const char[] error, any data)
{
	if (db == null)
	{
		LogError("[l4d2mgr_country_filter] DB connect failed: %s", error);
		g_hDB = null;
		return;
	}

	g_hDB = db;
	RefreshBlocklist();

	if (g_hTimerRefresh == null)
	{
		g_hTimerRefresh = CreateTimer(REFRESH_INTERVAL, Timer_Refresh, _, TIMER_REPEAT);
	}
}

public Action Timer_Refresh(Handle timer)
{
	RefreshBlocklist();
	return Plugin_Continue;
}

void RefreshBlocklist()
{
	if (g_hDB == null)
	{
		ConnectDatabase();
		return;
	}

	g_hDB.Query(OnRefreshResult, "SELECT country_code FROM country_filter_blocklist");
}

void OnRefreshResult(Database db, DBResultSet results, const char[] error, any data)
{
	if (results == null)
	{
		LogError("[l4d2mgr_country_filter] Blocklist refresh query failed: %s", error);
		return;
	}

	StringMap newMap = new StringMap();

	while (results.FetchRow())
	{
		char sCode[8];
		results.FetchString(0, sCode, sizeof(sCode));

		if (sCode[0] != '\0')
		{
			newMap.SetValue(sCode, true);
		}
	}

	if (g_hBlocklist != null)
	{
		delete g_hBlocklist;
	}
	g_hBlocklist = newMap;
}

// --- 接続フィルタリング ----------------------------------------
// 要確認: OnClientPreAdminCheck内でのRejectClientの有効性は
// l4d2mgr_modelockの実装で実証済みという前提で書いている。
// 未確認のためdevgame-svでの実コンパイル・実接続テストが必須。

public Action OnClientPreAdminCheck(int client)
{
	if (!g_bEnabled || g_hBlocklist == null)
	{
		return Plugin_Continue;
	}

	char sCode[8];
	GeoipCode2(client, sCode);

	if (sCode[0] == '\0')
	{
		return Plugin_Continue;
	}

	if (g_hBlocklist.ContainsKey(sCode))
	{
		char sIP[64], sSteamID[32], sTime[32], sReason[128];

		GetClientIP(client, sIP, sizeof(sIP));
		GetClientAuthId(client, AuthId_Steam2, sSteamID, sizeof(sSteamID));
		FormatTime(sTime, sizeof(sTime), "%Y-%m-%d %H:%M:%S", GetTime());

		LogToFile(LOG_FILE, "%s, %s, %s, %s", sTime, sIP, sCode, sSteamID);

		FormatEx(sReason, sizeof(sReason),
			"Connections from your region (%s) are not permitted on this server.", sCode);
		RejectClient(client, sReason);
	}

	return Plugin_Continue;
}
