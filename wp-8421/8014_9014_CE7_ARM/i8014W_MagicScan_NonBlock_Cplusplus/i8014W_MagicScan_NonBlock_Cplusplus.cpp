// complete_magicscan_loop_send_nonblock_wince_12ch.cpp
// One EXE (VS2008 / WinCE/WEC7 friendly):
// every 10 minutes -> MagicScan (CH0~CH11, 10kHz/ch, 5s) -> write burst.tmp -> rename burst.bin -> TCP send burst.bin
//
// NOTE:
// This version assumes your actual hardware/API supports 12 scan channels (CH0~CH11).
// If your module is still I-8014W and it does NOT support 12 analog input channels,
// this code structure is correct, but the hardware will still fail at runtime.

#include "stdafx.h"
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <tchar.h>

#include "..\\Lib\\pac_i8014W.h"
#pragma comment(lib,"..\\Lib\\pac_i8014W.lib")

#include <winsock2.h>
#pragma comment(lib, "ws2.lib")

// =============================
// User config (EDIT THESE)
// =============================
static const char* kServerIp = "192.168.1.10";
static const unsigned short kServerPort = 9000;

// Overwrite strategy (relative path)
static const wchar_t* kTmpNameW = L"burst.tmp";
static const wchar_t* kBinNameW = L"burst.bin";

// Schedule
static const DWORD kIntervalMs = 10UL * 60UL * 1000UL; // 10 min

// Acquisition fixed params
static const int   kMaxSlots = 8;
static const short kScanChCount = 12;

// 12 channels: CH0 ~ CH11
static const short kChannelList[12] = {
    0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11
};

static const int   kGain = 0;             // 0:+/-10V (change if needed)
static const int   kScanMode = 1;         // 1=M1 Standard
static const int   kTriggerSource = 0;    // 0=Software
static const int   kTriggerState  = 0;

static const float kPerChannelHz = 10000.0f;
static const float kSeconds = 1.0f;

// Non-block ReadFIFO: max samples per call (aggregate samples, interleaved)
static const short kReadCnt = 4096;

// Safety timeout (acquire window + margin)
static const DWORD kAcquireTimeoutMs = (DWORD)(kSeconds * 1000.0f) + 5000; // +5s margin

#pragma pack(push, 1)
struct BurstHeaderV1 {
    char magic[8];              // "I8014W\0"
    unsigned int version;       // 1
    unsigned int headerBytes;   // sizeof(BurstHeaderV1)

    unsigned int slotIndex;
    unsigned int scanChCount;   // 12
    short chList[16];
    short gainList[16];

    float perChannelHz;
    float requestedAggHz;
    float realAggHz;
    float seconds;
    unsigned int totalSamples;  // aggregate samples written (interleaved)

    SYSTEMTIME startTime;
};
#pragma pack(pop)

// -----------------------------
// Utilities
// -----------------------------
static int FindFirstI8014W()
{
    for (int slot = 0; slot < kMaxSlots; ++slot) {
        if (pac_i8014W_Init((short)slot) == 0) return slot;
    }
    return -1;
}

static bool SafeRenameTmpToBin(const wchar_t* tmpW, const wchar_t* binW)
{
    DeleteFileW(binW);
    return MoveFileW(tmpW, binW) ? true : false;
}

static bool TcpSendAll(SOCKET s, const unsigned char* data, int len)
{
    int sent = 0;
    while (sent < len) {
        int n = send(s, (const char*)data + sent, len - sent, 0);
        if (n <= 0) return false;
        sent += n;
    }
    return true;
}

// Stream file -> socket
// Protocol: [4 bytes 'B''I''N''1'] [4 bytes fileSize LE] [file bytes...]
static bool SendFileOverTcp_Stream(const char* serverIp, unsigned short port, const wchar_t* filePathW)
{
    HANDLE h = CreateFileW(filePathW, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
    if (h == INVALID_HANDLE_VALUE) {
        printf("[TCP] Open file failed.\n");
        return false;
    }

    DWORD fileSize = GetFileSize(h, NULL);
    if (fileSize == INVALID_FILE_SIZE || fileSize == 0) {
        CloseHandle(h);
        printf("[TCP] File size invalid.\n");
        return false;
    }

    SOCKET s = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (s == INVALID_SOCKET) {
        printf("[TCP] socket() failed, err=%d\n", WSAGetLastError());
        CloseHandle(h);
        return false;
    }

    sockaddr_in addr;
    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_port = htons(port);
    addr.sin_addr.s_addr = inet_addr(serverIp);
    if (addr.sin_addr.s_addr == INADDR_NONE) {
        printf("[TCP] Invalid server IP.\n");
        closesocket(s);
        CloseHandle(h);
        return false;
    }

    if (connect(s, (sockaddr*)&addr, sizeof(addr)) != 0) {
        printf("[TCP] connect() failed, err=%d\n", WSAGetLastError());
        closesocket(s);
        CloseHandle(h);
        return false;
    }

    unsigned char hdr[8];
    hdr[0] = 'B'; hdr[1] = 'I'; hdr[2] = 'N'; hdr[3] = '1';
    hdr[4] = (unsigned char)(fileSize & 0xFF);
    hdr[5] = (unsigned char)((fileSize >> 8) & 0xFF);
    hdr[6] = (unsigned char)((fileSize >> 16) & 0xFF);
    hdr[7] = (unsigned char)((fileSize >> 24) & 0xFF);

    if (!TcpSendAll(s, hdr, 8)) {
        printf("[TCP] send header failed, err=%d\n", WSAGetLastError());
        shutdown(s, SD_BOTH);
        closesocket(s);
        CloseHandle(h);
        return false;
    }

    const DWORD kBufBytes = 8192;
    unsigned char* buf = (unsigned char*)malloc(kBufBytes);
    if (!buf) {
        shutdown(s, SD_BOTH);
        closesocket(s);
        CloseHandle(h);
        return false;
    }

    DWORD totalSent = 0;
    bool ok = true;
    while (totalSent < fileSize) {
        DWORD toRead = kBufBytes;
        DWORD remain = fileSize - totalSent;
        if (remain < toRead) toRead = remain;

        DWORD readBytes = 0;
        if (!ReadFile(h, buf, toRead, &readBytes, NULL) || readBytes == 0) {
            ok = false;
            break;
        }
        if (!TcpSendAll(s, buf, (int)readBytes)) {
            ok = false;
            break;
        }
        totalSent += readBytes;
    }

    free(buf);
    shutdown(s, SD_BOTH);
    closesocket(s);
    CloseHandle(h);

    if (!ok) {
        printf("[TCP] send file failed, err=%d\n", WSAGetLastError());
        return false;
    }

    printf("[TCP] Sent %lu bytes OK.\n", (unsigned long)fileSize);
    return true;
}

// -----------------------------
// Acquisition (NonBlock ReadFIFO -> write tmp -> rename)
// -----------------------------
static int CaptureBurstToTmpThenRename_NonBlock(int slotIndex, const wchar_t* tmpW, const wchar_t* binW)
{
    short chArr[16] = {0};
    short gainArr[16] = {0};

    for (int i = 0; i < kScanChCount; ++i) {
        chArr[i] = kChannelList[i];
        gainArr[i] = (short)kGain;
    }

    const float requestedAggHz = kPerChannelHz * (float)kScanChCount; // 120k for 12ch
    float realAggHz = 0.0f;

    pac_i8014W_ConfigMagicScan(
        (short)slotIndex,
        chArr,
        gainArr,
        kScanChCount,
        requestedAggHz,
        kScanMode,
        kTriggerSource,
        kTriggerState,
        &realAggHz
    );

    if (realAggHz <= 0.0f) {
        printf("[ACQ] ERROR: ConfigMagicScan realAggHz invalid.\n");
        return -101;
    }

    const unsigned long targetTotal = (unsigned long)(realAggHz * kSeconds + 0.5f);
    if (targetTotal == 0) {
        printf("[ACQ] ERROR: targetTotal=0.\n");
        return -102;
    }

    FILE* fp = _wfopen(tmpW, L"wb+");
    if (!fp) {
        printf("[ACQ] ERROR: cannot open tmp for write.\n");
        return -103;
    }

    BurstHeaderV1 hdr;
    memset(&hdr, 0, sizeof(hdr));
    memcpy(hdr.magic, "I8014W\0", 7);
    hdr.version = 1;
    hdr.headerBytes = (unsigned int)sizeof(BurstHeaderV1);
    hdr.slotIndex = (unsigned int)slotIndex;
    hdr.scanChCount = (unsigned int)kScanChCount;

    for (int i = 0; i < kScanChCount; ++i) {
        hdr.chList[i] = kChannelList[i];
        hdr.gainList[i] = (short)kGain;
    }

    hdr.perChannelHz = kPerChannelHz;
    hdr.requestedAggHz = requestedAggHz;
    hdr.realAggHz = realAggHz;
    hdr.seconds = kSeconds;
    hdr.totalSamples = 0;
    GetLocalTime(&hdr.startTime);

    if (fwrite(&hdr, 1, sizeof(hdr), fp) != sizeof(hdr)) {
        printf("[ACQ] ERROR: write header failed.\n");
        fclose(fp);
        return -104;
    }

    pac_i8014W_StopMagicScan((short)slotIndex);
    pac_i8014W_ClearFIFO((short)slotIndex);

    short startRet = pac_i8014W_StartMagicScan((short)slotIndex);
    if (startRet != 0) {
        printf("[ACQ] ERROR: StartMagicScan ret=%d\n", startRet);
        fclose(fp);
        return -200;
    }

    short buffer[kReadCnt];
    unsigned long totalRead = 0;

    DWORD tStart = GetTickCount();
    DWORD timeoutMs = kAcquireTimeoutMs;

    while (totalRead < targetTotal) {
        DWORD tNow = GetTickCount();
        if ((tNow - tStart) > timeoutMs) {
            printf("[ACQ] TIMEOUT: Read %lu / %lu.\n",
                   (unsigned long)totalRead, (unsigned long)targetTotal);
            pac_i8014W_StopMagicScan((short)slotIndex);
            fclose(fp);
            return -999;
        }

        unsigned long remain = targetTotal - totalRead;
        short want = (short)((remain < (unsigned long)kReadCnt) ? remain : (unsigned long)kReadCnt);
        short got = 0;

        short ret = pac_i8014W_ReadFIFO((short)slotIndex, buffer, want, &got);

        if (ret == -5) {
            Sleep(1);
            continue;
        }

        if (ret == -6) {
            printf("[ACQ] WARN: FIFO_LATCHED/Overflow (ret=%d). Data is not continuous.\n", ret);
            pac_i8014W_StopMagicScan((short)slotIndex);
            pac_i8014W_ClearFIFO((short)slotIndex);
            fclose(fp);
            return -203;
        }

        if (ret != 0) {
            printf("[ACQ] ERROR: ReadFIFO ret=%d\n", ret);
            pac_i8014W_StopMagicScan((short)slotIndex);
            fclose(fp);
            return -201;
        }

        if (got <= 0) {
            Sleep(1);
            continue;
        }

        size_t wrote = fwrite(buffer, sizeof(short), (size_t)got, fp);
        if (wrote != (size_t)got) {
            printf("[ACQ] ERROR: fwrite failed.\n");
            pac_i8014W_StopMagicScan((short)slotIndex);
            fclose(fp);
            return -202;
        }

        totalRead += (unsigned long)got;
    }

    short stopRet = pac_i8014W_StopMagicScan((short)slotIndex);
    if (stopRet != 0) {
        printf("[ACQ] WARN: StopMagicScan ret=%d\n", stopRet);
    }

    hdr.totalSamples = (unsigned int)totalRead;
    fseek(fp, 0, SEEK_SET);
    fwrite(&hdr, 1, sizeof(hdr), fp);
    fflush(fp);
    fclose(fp);

    if (!SafeRenameTmpToBin(tmpW, binW)) {
        printf("[ACQ] ERROR: rename tmp->bin failed.\n");
        return -300;
    }

    printf("[ACQ] OK realAggHz=%.3f, target=%lu samples, wrote=%lu samples, file=%ls\n",
           realAggHz, (unsigned long)targetTotal, (unsigned long)totalRead, binW);

    return 0;
}

// -----------------------------
// Scheduler
// -----------------------------
static void RunLoop(int slotIndex)
{
    DWORD nextTick = GetTickCount();
    while (1) {
        DWORD now = GetTickCount();
        if ((long)(now - nextTick) >= 0) {
            printf("===== Cycle start =====\n");

            DWORD t0 = GetTickCount();
            int rc = CaptureBurstToTmpThenRename_NonBlock(slotIndex, kTmpNameW, kBinNameW);
            DWORD t1 = GetTickCount();

            if (rc != 0) {
                printf("[ACQ] FAILED rc=%d (elapsed=%lu ms)\n", rc, (unsigned long)(t1 - t0));
            } else {
                printf("[ACQ] DONE (elapsed=%lu ms)\n", (unsigned long)(t1 - t0));

                bool sent = SendFileOverTcp_Stream(kServerIp, kServerPort, kBinNameW);
                printf("[TCP] %s\n", sent ? "OK" : "FAILED");
            }

            printf("===== Cycle end =====\n\n");

            nextTick += kIntervalMs;
        }
        Sleep(500);
    }
}

int _tmain(int argc, _TCHAR* argv[])
{
    printf("Periodic burst (NonBlock ReadFIFO): CH0~CH11, 10kHz/ch, 5s, every 10 minutes\n");
    printf("Output: %ls (overwrite)\n", kBinNameW);
    printf("Server: %s:%u\n", kServerIp, (unsigned)kServerPort);

    WSADATA wsa;
    if (WSAStartup(MAKEWORD(2,2), &wsa) != 0) {
        printf("WSAStartup failed, err=%d\n", WSAGetLastError());
        return 1;
    }

    int slot = FindFirstI8014W();
    if (slot < 0) {
        printf("ERROR: No module found in slots 0..7\n");
        WSACleanup();
        return 2;
    }
    printf("Found module at slot %d\n", slot);

    RunLoop(slot);

    WSACleanup();
    return 0;
}