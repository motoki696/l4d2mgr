#pragma semicolon 1
#pragma newdecls required

#include <sourcemod>
#include <sdktools>
#include <l4d2mgr_ac>

public Plugin myinfo =
{
    name = "L4D2 Manager: AC Speedhack",
    author = "motoki",
    description = "Speedhack detector (usercmd rate)",
    version = "0.2.0",
    url = ""
};

ConVar g_cvarEnabled;
ConVar g_cvarWindow;
ConVar g_cvarSpeedRatio;
ConVar g_cvarStrikes;
ConVar g_cvarGrace;
ConVar g_cvarMaxLoss;
ConVar g_cvarDebug;

int g_cmdCount[MAXPLAYERS+1];
float g_windowStart[MAXPLAYERS+1];
int g_strikes[MAXPLAYERS+1];
float g_maxRatio[MAXPLAYERS+1];

public void OnPluginStart()
{
    g_cvarEnabled = CreateConVar("l4d2mgr_ac_speed_enable", "1",
        "Enable speedhack detector", 0, true, 0.0, true, 1.0);
    g_cvarWindow = CreateConVar("l4d2mgr_ac_speed_window", "5.0",
        "Measurement window seconds", 0, true, 2.0, true, 30.0);
    g_cvarSpeedRatio = CreateConVar("l4d2mgr_ac_speed_ratio", "1.25",
        "Threshold of (cmds per second / tickrate)", 0, true, 1.05, true, 5.0);
    g_cvarStrikes = CreateConVar("l4d2mgr_ac_speed_strikes", "3",
        "Consecutive windows above threshold before reporting", 0, true, 1.0, true, 20.0);
    g_cvarGrace = CreateConVar("l4d2mgr_ac_speed_grace", "30.0",
        "Ignore clients connected for less than this many seconds", 0, true, 0.0, true, 300.0);
    g_cvarMaxLoss = CreateConVar("l4d2mgr_ac_speed_maxloss", "0.10",
        "Skip windows when average packet loss is above this", 0, true, 0.0, true, 1.0);
    g_cvarDebug = CreateConVar("l4d2mgr_ac_speed_debug", "0",
        "Log every measurement window (0/1)", 0, true, 0.0, true, 1.0);

    AutoExecConfig(true, "l4d2mgr_ac_speedhack");
}

public void OnClientPutInServer(int client)
{
    g_cmdCount[client] = 0;
    g_strikes[client] = 0;
    g_maxRatio[client] = 0.0;
    g_windowStart[client] = GetEngineTime();
}

public void OnClientDisconnect(int client)
{
    g_cmdCount[client] = 0;
    g_strikes[client] = 0;
    g_maxRatio[client] = 0.0;
    g_windowStart[client] = GetEngineTime();
}

public void OnPlayerRunCmdPost(int client, int buttons, int impulse, const float vel[3], const float angles[3],
    int weapon, int subtype, int cmdnum, int tickcount, int seed, const int mouse[2])
{
    if (!g_cvarEnabled.BoolValue || !IsClientInGame(client) || IsFakeClient(client))
    {
        return;
    }

    g_cmdCount[client]++;

    float now = GetEngineTime();
    float elapsed = now - g_windowStart[client];
    float window = g_cvarWindow.FloatValue;

    if (elapsed < window)
    {
        return;
    }

    float tickrate = 1.0 / GetTickInterval();
    float rate = float(g_cmdCount[client]) / elapsed;
    float ratio = rate / tickrate;

    float grace = g_cvarGrace.FloatValue;
    float maxloss = g_cvarMaxLoss.FloatValue;

    float loss = GetClientAvgLoss(client, NetFlow_Both);
    char skip[32];
    skip[0] = '\0';
    if (GetClientTime(client) < grace)
    {
        strcopy(skip, sizeof(skip), "grace");
    }
    else if (IsClientTimingOut(client))
    {
        strcopy(skip, sizeof(skip), "timingout");
    }
    else if (loss > maxloss)
    {
        FormatEx(skip, sizeof(skip), "loss=%.2f", loss);
    }
    else if (elapsed > window * 3.0)
    {
        FormatEx(skip, sizeof(skip), "stall=%.1fs", elapsed);
    }

    if (skip[0] != '\0')
    {
        if (g_cvarDebug.BoolValue)
        {
            LogMessage("[AC-SPEED] %N cmd/s=%.1f tickrate=%.0f ratio=%.2f SKIP %s", client, rate, tickrate, ratio, skip);
        }
        g_cmdCount[client] = 0;
        g_windowStart[client] = now;
        return;
    }

    float threshold = g_cvarSpeedRatio.FloatValue;

    if (ratio >= threshold)
    {
        g_strikes[client]++;
        if (ratio > g_maxRatio[client])
        {
            g_maxRatio[client] = ratio;
        }
    }
    else
    {
        g_strikes[client] = 0;
        g_maxRatio[client] = 0.0;
    }

    if (g_cvarDebug.BoolValue)
    {
        LogMessage("[AC-SPEED] %N cmd/s=%.1f tickrate=%.0f ratio=%.2f strikes=%d/%d", client, rate, tickrate, ratio, g_strikes[client], g_cvarStrikes.IntValue);
    }

    if (g_strikes[client] >= g_cvarStrikes.IntValue)
    {
        int severity = 1;
        if (g_maxRatio[client] >= 2.0)
        {
            severity = 3;
        }
        else if (g_maxRatio[client] >= 1.5)
        {
            severity = 2;
        }

        char detail[256];
        FormatEx(detail, sizeof(detail), "cmd/s=%.1f tickrate=%.0f ratio=%.2f max=%.2f windows=%d",
            rate, tickrate, ratio, g_maxRatio[client], g_strikes[client]);

        L4D2AC_Report(client, "speedhack", severity, detail);

        g_strikes[client] = 0;
        g_maxRatio[client] = 0.0;
    }

    g_cmdCount[client] = 0;
    g_windowStart[client] = now;
}
