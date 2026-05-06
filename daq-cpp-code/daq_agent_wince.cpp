// daq_agent_wince.cpp
// VS2008 / WinCE / WEC7 friendly
//
// PAC side TCP command server:
//   - listen on TCP port 9000
//   - support text commands:
//       PING
//       STATUS
//       START_CAPTURE CH=12 RATE=10000 SEC=10 RTU1=1 RTU2=2
//   - START_CAPTURE flow:
//       1) read Modbus RTU address RTU1 once
//       2) read Modbus RTU address RTU2 once, RTU2=0 means disabled
//       3) capture I-8014W DAQ into memory
//       4) return 48-byte DaqPacketHeader + raw int16 DAQ payload
//
// Notes:
//   - No burst.bin is generated.
//   - TCP server is single-client, one-command-per-connection.
//   - DAQ payload is int16 interleaved:
//       sample0_ch0, sample0_ch1, ... sample0_chN,
//       sample1_ch0, sample1_ch1, ...

#include "stdafx.h"

#include <windows.h>
#include <winsock2.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <tchar.h>

#pragma comment(lib, "ws2.lib")

#include "..\\Lib\\pac_i8014W.h"
#pragma comment(lib,"..\\Lib\\pac_i8014W.lib")

// =====================================================
// Fixed PAC-side settings
// =====================================================
static const unsigned short kListenPort = 9000;
static const unsigned char  kMachineId  = 1;

static const int kMaxSlots = 8;
static const int kMaxChannelCount = 12;      // This file is prepared for CH0~CH11.
static const int kGain = 0;                  // 0: +/-10V, change only if your wiring requires it.
static const int kScanMode = 1;              // 1: M1 Standard
static const int kTriggerSource = 0;         // 0: Software
static const int kTriggerState  = 0;
static const short kReadCnt = 4096;          // aggregate samples per ReadFIFO call

// Modbus RTU fixed communication setting.
// RTU addresses are NOT fixed here; they come from START_CAPTURE RTU1/RTU2.
static const TCHAR* kModbusComName1 = TEXT("COM2:");
static const TCHAR* kModbusComName2 = TEXT("COM2");   // fallback for some CE drivers
static const DWORD kModbusBaudRate  = 9600;
static const BYTE  kModbusParity    = 1;               // 0=None, 1=Odd, 2=Even
static const WORD  kModbusStartAddr = 0x0008;          // DCT531 actual pressure register
static const WORD  kModbusRegCount  = 0x0002;          // 32-bit float = 2 registers
static const DWORD kModbusRespLen   = 9;               // id + fn + byte count + 4 data + CRC

// =====================================================
// Status / error codes
// =====================================================
#define AGENT_STATE_IDLE   0
#define AGENT_STATE_BUSY   1
#define AGENT_STATE_ERROR  2

#define HDR_STATUS_OK           0
#define HDR_STATUS_DAQ_ERROR    1
#define HDR_STATUS_BUSY         2
#define HDR_STATUS_BAD_COMMAND  3

#define DATA_TYPE_INT16_INTERLEAVED 1

#define RTU_OK          0
#define RTU_TIMEOUT     1
#define RTU_CRC_ERROR   2
#define RTU_ERROR       3
#define RTU_DISABLED    4

// =====================================================
// Packet header, exactly 48 bytes with pack(1)
// =====================================================
#pragma pack(push, 1)
struct DaqPacketHeader
{
    char magic[4];              // "DAQ1"

    unsigned short version;     // 1
    unsigned short headerBytes; // sizeof(DaqPacketHeader), 48

    unsigned char machineId;    // fixed kMachineId
    unsigned char status;       // 0=OK, 1=DAQ_ERROR, 2=BUSY, 3=BAD_COMMAND
    unsigned char channelCount; // CH
    unsigned char dataType;     // 1=int16 interleaved

    unsigned int requestedSampleRateHz; // RATE
    float actualSampleRateHz;           // realAggHz / channelCount

    unsigned int samplesPerChannel;     // RATE * SEC
    unsigned int payloadBytes;          // CH * samplesPerChannel * sizeof(short)
    unsigned int seqNo;                 // increment per START_CAPTURE

    unsigned char rtuAddr1;             // RTU1
    unsigned char rtuStatus1;           // 0=OK, 1=TIMEOUT, 2=CRC_ERROR, 3=ERROR, 4=DISABLED
    unsigned char rtuAddr2;             // RTU2
    unsigned char rtuStatus2;

    float rtuValue1;                    // RTU1 value if status OK
    float rtuValue2;                    // RTU2 value if status OK

    unsigned int errorCode;             // DAQ error code; 0 if OK
};
#pragma pack(pop)

// Compile-time sanity note: this should be 48 bytes.
// VS2008 does not always support static_assert, so runtime print/check is used.

struct CaptureRequest
{
    int channelCount;
    int requestedSampleRateHz;
    int seconds;
    int samplesPerChannel;
    unsigned char rtuAddr1;
    unsigned char rtuAddr2;
};

static volatile int gAgentState = AGENT_STATE_IDLE;
static unsigned int gSeqNo = 0;
static HANDLE gModbusCom = INVALID_HANDLE_VALUE;

// =====================================================
// Basic utilities
// =====================================================
static const char* StateText()
{
    if (gAgentState == AGENT_STATE_IDLE)  return "IDLE\n";
    if (gAgentState == AGENT_STATE_BUSY)  return "BUSY\n";
    if (gAgentState == AGENT_STATE_ERROR) return "ERROR\n";
    return "UNKNOWN\n";
}

static BOOL StartsWith(const char* s, const char* prefix)
{
    size_t n = strlen(prefix);
    return (strncmp(s, prefix, n) == 0) ? TRUE : FALSE;
}

static BOOL SendAll(SOCKET s, const unsigned char* data, int totalBytes)
{
    int sentTotal = 0;

    while (sentTotal < totalBytes)
    {
        int n = send(s, (const char*)data + sentTotal, totalBytes - sentTotal, 0);
        if (n <= 0) return FALSE;
        sentTotal += n;
    }

    return TRUE;
}

static BOOL SendText(SOCKET s, const char* text)
{
    return SendAll(s, (const unsigned char*)text, (int)strlen(text));
}

static BOOL RecvCommandLine(SOCKET s, char* outCmd, int outSize)
{
    int pos = 0;

    if (outCmd == NULL || outSize <= 1) return FALSE;
    memset(outCmd, 0, outSize);

    while (pos < outSize - 1)
    {
        char c = 0;
        int n = recv(s, &c, 1, 0);
        if (n <= 0) return FALSE;

        if (c == '\n') break;
        if (c == '\r') continue;

        outCmd[pos++] = c;
    }

    outCmd[pos] = '\0';
    return (pos > 0) ? TRUE : FALSE;
}

static BOOL ParseKeyInt(const char* cmd, const char* key, int* outVal)
{
    const char* p;
    int v;

    if (cmd == NULL || key == NULL || outVal == NULL) return FALSE;

    p = strstr(cmd, key);
    if (p == NULL) return FALSE;

    p += strlen(key);
    v = atoi(p);
    *outVal = v;
    return TRUE;
}

static BOOL ParseStartCaptureCommand(const char* cmd, CaptureRequest* req)
{
    int ch = 0;
    int rate = 0;
    int sec = 0;
    int rtu1 = 0;
    int rtu2 = 0;
    unsigned long totalSamples;
    unsigned long payloadBytes;

    if (cmd == NULL || req == NULL) return FALSE;

    memset(req, 0, sizeof(CaptureRequest));

    if (!StartsWith(cmd, "START_CAPTURE")) return FALSE;
    if (!ParseKeyInt(cmd, "CH=", &ch)) return FALSE;
    if (!ParseKeyInt(cmd, "RATE=", &rate)) return FALSE;
    if (!ParseKeyInt(cmd, "SEC=", &sec)) return FALSE;
    if (!ParseKeyInt(cmd, "RTU1=", &rtu1)) return FALSE;
    if (!ParseKeyInt(cmd, "RTU2=", &rtu2)) return FALSE;

    // First-version limits. Adjust later only after hardware validation.
    if (ch <= 0 || ch > kMaxChannelCount) return FALSE;
    if (rate <= 0 || rate > 100000) return FALSE;
    if (sec <= 0 || sec > 60) return FALSE;
    if (rtu1 < 0 || rtu1 > 247) return FALSE;
    if (rtu2 < 0 || rtu2 > 247) return FALSE;

    req->channelCount = ch;
    req->requestedSampleRateHz = rate;
    req->seconds = sec;
    req->samplesPerChannel = rate * sec;
    req->rtuAddr1 = (unsigned char)rtu1;
    req->rtuAddr2 = (unsigned char)rtu2;

    totalSamples = (unsigned long)req->samplesPerChannel * (unsigned long)req->channelCount;
    payloadBytes = totalSamples * sizeof(short);

    if (totalSamples == 0 || payloadBytes == 0) return FALSE;
    if (payloadBytes > 32UL * 1024UL * 1024UL) return FALSE; // safety guard

    return TRUE;
}

static void FillBasicHeader(DaqPacketHeader* h, const CaptureRequest* req, unsigned int seqNo)
{
    memset(h, 0, sizeof(DaqPacketHeader));

    h->magic[0] = 'D';
    h->magic[1] = 'A';
    h->magic[2] = 'Q';
    h->magic[3] = '1';

    h->version = 1;
    h->headerBytes = (unsigned short)sizeof(DaqPacketHeader);

    h->machineId = kMachineId;
    h->status = HDR_STATUS_OK;
    h->channelCount = (unsigned char)req->channelCount;
    h->dataType = DATA_TYPE_INT16_INTERLEAVED;

    h->requestedSampleRateHz = (unsigned int)req->requestedSampleRateHz;
    h->actualSampleRateHz = 0.0f;

    h->samplesPerChannel = (unsigned int)req->samplesPerChannel;
    h->payloadBytes = (unsigned int)(req->channelCount * req->samplesPerChannel * sizeof(short));
    h->seqNo = seqNo;

    h->rtuAddr1 = req->rtuAddr1;
    h->rtuStatus1 = RTU_DISABLED;
    h->rtuAddr2 = req->rtuAddr2;
    h->rtuStatus2 = RTU_DISABLED;

    h->rtuValue1 = 0.0f;
    h->rtuValue2 = 0.0f;
    h->errorCode = 0;
}

// =====================================================
// Modbus RTU / DCT531
// =====================================================
static unsigned short ModbusCRC16(const unsigned char* data, int len)
{
    unsigned short crc = 0xFFFF;
    int i, j;

    for (i = 0; i < len; ++i)
    {
        crc ^= data[i];
        for (j = 0; j < 8; ++j)
        {
            if (crc & 0x0001)
            {
                crc >>= 1;
                crc ^= 0xA001;
            }
            else
            {
                crc >>= 1;
            }
        }
    }

    return crc;
}

static BOOL CheckModbusCRC(const unsigned char* buf, int len)
{
    unsigned short crcCalc;
    unsigned short crcRecv;

    if (buf == NULL || len < 3) return FALSE;

    crcCalc = ModbusCRC16(buf, len - 2);
    crcRecv = (unsigned short)buf[len - 2] | ((unsigned short)buf[len - 1] << 8);

    return (crcCalc == crcRecv) ? TRUE : FALSE;
}

static BOOL ConfigureModbusPort(HANDLE hCom)
{
    DCB dcb;
    COMMTIMEOUTS timeouts;
    BOOL ok;

    SetupComm(hCom, 256, 256);
    PurgeComm(hCom, PURGE_RXCLEAR | PURGE_TXCLEAR);

    ZeroMemory(&dcb, sizeof(dcb));
    dcb.DCBlength = sizeof(dcb);

    ok = GetCommState(hCom, &dcb);
    if (!ok)
    {
        printf("[RTU] GetCommState failed, err=%lu\n", GetLastError());
        return FALSE;
    }

    dcb.BaudRate = kModbusBaudRate;
    dcb.ByteSize = 8;
    dcb.StopBits = ONESTOPBIT;
    dcb.fBinary = TRUE;

    if (kModbusParity == 0)
    {
        dcb.Parity = NOPARITY;
        dcb.fParity = FALSE;
    }
    else if (kModbusParity == 1)
    {
        dcb.Parity = ODDPARITY;
        dcb.fParity = TRUE;
    }
    else if (kModbusParity == 2)
    {
        dcb.Parity = EVENPARITY;
        dcb.fParity = TRUE;
    }
    else
    {
        return FALSE;
    }

    dcb.fOutxCtsFlow = FALSE;
    dcb.fOutxDsrFlow = FALSE;
    dcb.fDtrControl = DTR_CONTROL_DISABLE;
    dcb.fDsrSensitivity = FALSE;
    dcb.fTXContinueOnXoff = TRUE;
    dcb.fOutX = FALSE;
    dcb.fInX = FALSE;
    dcb.fRtsControl = RTS_CONTROL_DISABLE;
    dcb.fAbortOnError = FALSE;

    ok = SetCommState(hCom, &dcb);
    if (!ok)
    {
        printf("[RTU] SetCommState failed, err=%lu\n", GetLastError());
        return FALSE;
    }

    ZeroMemory(&timeouts, sizeof(timeouts));
    timeouts.ReadIntervalTimeout = 100;
    timeouts.ReadTotalTimeoutMultiplier = 0;
    timeouts.ReadTotalTimeoutConstant = 1000;  // 1 second response wait
    timeouts.WriteTotalTimeoutMultiplier = 0;
    timeouts.WriteTotalTimeoutConstant = 1000;

    ok = SetCommTimeouts(hCom, &timeouts);
    if (!ok)
    {
        printf("[RTU] SetCommTimeouts failed, err=%lu\n", GetLastError());
        return FALSE;
    }

    return TRUE;
}

static BOOL InitModbus()
{
    if (gModbusCom != INVALID_HANDLE_VALUE) return TRUE;

    gModbusCom = CreateFile(
        kModbusComName1,
        GENERIC_READ | GENERIC_WRITE,
        0,
        NULL,
        OPEN_EXISTING,
        0,
        NULL
    );

    if (gModbusCom == INVALID_HANDLE_VALUE)
    {
        printf("[RTU] Open COM2: failed, trying COM2. err=%lu\n", GetLastError());

        gModbusCom = CreateFile(
            kModbusComName2,
            GENERIC_READ | GENERIC_WRITE,
            0,
            NULL,
            OPEN_EXISTING,
            0,
            NULL
        );
    }

    if (gModbusCom == INVALID_HANDLE_VALUE)
    {
        printf("[RTU] Open Modbus COM failed, err=%lu\n", GetLastError());
        return FALSE;
    }

    if (!ConfigureModbusPort(gModbusCom))
    {
        CloseHandle(gModbusCom);
        gModbusCom = INVALID_HANDLE_VALUE;
        return FALSE;
    }

    Sleep(1000); // safer startup delay for RTU instrument
    printf("[RTU] Modbus opened: COM2, baud=%lu, parity=Odd\n", kModbusBaudRate);
    return TRUE;
}

static BOOL QueryDct531Once(unsigned char slaveId, unsigned char* resp, DWORD* pReaded)
{
    unsigned char req[8];
    unsigned short crc;
    DWORD written = 0;
    BOOL ok;

    if (gModbusCom == INVALID_HANDLE_VALUE) return FALSE;
    if (resp == NULL || pReaded == NULL) return FALSE;

    req[0] = slaveId;
    req[1] = 0x04; // Read Input Registers
    req[2] = (BYTE)((kModbusStartAddr >> 8) & 0xFF);
    req[3] = (BYTE)(kModbusStartAddr & 0xFF);
    req[4] = (BYTE)((kModbusRegCount >> 8) & 0xFF);
    req[5] = (BYTE)(kModbusRegCount & 0xFF);

    crc = ModbusCRC16(req, 6);
    req[6] = (BYTE)(crc & 0xFF);
    req[7] = (BYTE)((crc >> 8) & 0xFF);

    PurgeComm(gModbusCom, PURGE_RXCLEAR | PURGE_TXCLEAR);

    ok = WriteFile(gModbusCom, req, 8, &written, NULL);
    if (!ok || written != 8)
    {
        printf("[RTU] WriteFile failed. id=%u ok=%d written=%lu err=%lu\n",
               slaveId, ok, written, GetLastError());
        return FALSE;
    }

    ZeroMemory(resp, 32);
    *pReaded = 0;

    ok = ReadFile(gModbusCom, resp, kModbusRespLen, pReaded, NULL);
    if (!ok)
    {
        printf("[RTU] ReadFile failed. id=%u err=%lu\n", slaveId, GetLastError());
        return FALSE;
    }

    return TRUE;
}

// DCT531 pressure value is assumed to be IEEE754 float in response data bytes.
// Response layout: [id][04][04][b0][b1][b2][b3][crcL][crcH]
// Existing test showed data like 3E 5B B8 27, which is a big-endian float.
static BOOL ParsePressureFloatBE(const unsigned char* resp, DWORD readed, float* outValue)
{
    unsigned char le[4];

    if (resp == NULL || outValue == NULL) return FALSE;
    if (readed != kModbusRespLen) return FALSE;
    if (resp[2] != 0x04) return FALSE;

    // Convert Modbus big-endian float bytes to little-endian CPU memory.
    le[0] = resp[6];
    le[1] = resp[5];
    le[2] = resp[4];
    le[3] = resp[3];

    memcpy(outValue, le, 4);
    return TRUE;
}

static unsigned char ReadRtuValue(unsigned char slaveAddr, float* outValue)
{
    unsigned char resp[32];
    DWORD readed = 0;
    BOOL ok;

    if (outValue == NULL) return RTU_ERROR;
    *outValue = 0.0f;

    if (slaveAddr == 0) return RTU_DISABLED;

    if (gModbusCom == INVALID_HANDLE_VALUE)
    {
        if (!InitModbus()) return RTU_ERROR;
    }

    ok = QueryDct531Once(slaveAddr, resp, &readed);
    if (!ok) return RTU_ERROR;

    if (readed == 0) return RTU_TIMEOUT;

    if (readed >= 2 && (resp[1] & 0x80))
    {
        printf("[RTU] Modbus exception. id=%u code=%02X\n",
               slaveAddr, (readed >= 3 ? resp[2] : 0));
        return RTU_ERROR;
    }

    if (readed != kModbusRespLen)
    {
        printf("[RTU] Unexpected response length. id=%u readed=%lu\n", slaveAddr, readed);
        return RTU_ERROR;
    }

    if (!CheckModbusCRC(resp, (int)readed))
    {
        printf("[RTU] CRC error. id=%u\n", slaveAddr);
        return RTU_CRC_ERROR;
    }

    if (resp[0] != slaveAddr || resp[1] != 0x04)
    {
        printf("[RTU] Unexpected response id/function. id=%u respId=%u fn=%02X\n",
               slaveAddr, resp[0], resp[1]);
        return RTU_ERROR;
    }

    if (!ParsePressureFloatBE(resp, readed, outValue))
    {
        return RTU_ERROR;
    }

    return RTU_OK;
}

// =====================================================
// I-8014W acquisition
// =====================================================
static int FindFirstI8014W()
{
    int slot;
    for (slot = 0; slot < kMaxSlots; ++slot)
    {
        if (pac_i8014W_Init((short)slot) == 0) return slot;
    }
    return -1;
}

static int Capture8014WToMemory(
    int slotIndex,
    short* outBuffer,
    int channelCount,
    int requestedSampleRateHz,
    int samplesPerChannel,
    float* outRealAggHz)
{
    short chArr[16] = {0};
    short gainArr[16] = {0};
    int i;
    float requestedAggHz;
    float realAggHz = 0.0f;
    unsigned long targetTotal;
    unsigned long totalRead = 0;
    DWORD tStart;
    DWORD timeoutMs;
    short startRet;
    short buffer[kReadCnt];

    if (outBuffer == NULL) return -1;
    if (channelCount <= 0 || channelCount > kMaxChannelCount) return -2;
    if (requestedSampleRateHz <= 0) return -3;
    if (samplesPerChannel <= 0) return -4;

    if (outRealAggHz != NULL) *outRealAggHz = 0.0f;

    for (i = 0; i < channelCount; ++i)
    {
        chArr[i] = (short)i;       // CH0~CH(channelCount-1)
        gainArr[i] = (short)kGain;
    }

    requestedAggHz = (float)requestedSampleRateHz * (float)channelCount;

    pac_i8014W_ConfigMagicScan(
        (short)slotIndex,
        chArr,
        gainArr,
        (short)channelCount,
        requestedAggHz,
        kScanMode,
        kTriggerSource,
        kTriggerState,
        &realAggHz
    );

    if (realAggHz <= 0.0f)
    {
        printf("[DAQ] ERROR: ConfigMagicScan realAggHz invalid.\n");
        return -101;
    }

    if (outRealAggHz != NULL) *outRealAggHz = realAggHz;

    targetTotal = (unsigned long)samplesPerChannel * (unsigned long)channelCount;
    if (targetTotal == 0)
    {
        printf("[DAQ] ERROR: targetTotal=0.\n");
        return -102;
    }

    pac_i8014W_StopMagicScan((short)slotIndex);
    pac_i8014W_ClearFIFO((short)slotIndex);

    startRet = pac_i8014W_StartMagicScan((short)slotIndex);
    if (startRet != 0)
    {
        printf("[DAQ] ERROR: StartMagicScan ret=%d\n", startRet);
        return -200;
    }

    tStart = GetTickCount();
    timeoutMs = (DWORD)((samplesPerChannel * 1000UL) / (unsigned long)requestedSampleRateHz) + 10000UL;

    printf("[DAQ] Start capture: slot=%d CH=%d RATE=%d samples/ch=%d target=%lu realAggHz=%.3f\n",
           slotIndex, channelCount, requestedSampleRateHz, samplesPerChannel,
           (unsigned long)targetTotal, realAggHz);

    while (totalRead < targetTotal)
    {
        DWORD tNow = GetTickCount();
        unsigned long remain;
        short want;
        short got = 0;
        short ret;

        if ((tNow - tStart) > timeoutMs)
        {
            printf("[DAQ] TIMEOUT: read %lu / %lu\n", totalRead, targetTotal);
            pac_i8014W_StopMagicScan((short)slotIndex);
            return -999;
        }

        remain = targetTotal - totalRead;
        want = (short)((remain < (unsigned long)kReadCnt) ? remain : (unsigned long)kReadCnt);

        ret = pac_i8014W_ReadFIFO((short)slotIndex, buffer, want, &got);

        if (ret == -5)
        {
            Sleep(1);
            continue;
        }

        if (ret == -6)
        {
            printf("[DAQ] ERROR: FIFO overflow/latch ret=%d\n", ret);
            pac_i8014W_StopMagicScan((short)slotIndex);
            pac_i8014W_ClearFIFO((short)slotIndex);
            return -203;
        }

        if (ret != 0)
        {
            printf("[DAQ] ERROR: ReadFIFO ret=%d\n", ret);
            pac_i8014W_StopMagicScan((short)slotIndex);
            return -201;
        }

        if (got <= 0)
        {
            Sleep(1);
            continue;
        }

        memcpy(outBuffer + totalRead, buffer, (size_t)got * sizeof(short));
        totalRead += (unsigned long)got;
    }

    {
        short stopRet = pac_i8014W_StopMagicScan((short)slotIndex);
        if (stopRet != 0)
        {
            printf("[DAQ] WARN: StopMagicScan ret=%d\n", stopRet);
        }
    }

    printf("[DAQ] OK: read %lu samples.\n", totalRead);
    return 0;
}

// =====================================================
// TCP server
// =====================================================
static SOCKET StartTcpServer(unsigned short port)
{
    SOCKET s;
    sockaddr_in addr;
    int opt = 1;

    s = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (s == INVALID_SOCKET)
    {
        printf("[TCP] socket failed, err=%d\n", WSAGetLastError());
        return INVALID_SOCKET;
    }

    setsockopt(s, SOL_SOCKET, SO_REUSEADDR, (const char*)&opt, sizeof(opt));

    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_port = htons(port);
    addr.sin_addr.s_addr = htonl(INADDR_ANY);

    if (bind(s, (sockaddr*)&addr, sizeof(addr)) != 0)
    {
        printf("[TCP] bind failed, port=%u err=%d\n", (unsigned)port, WSAGetLastError());
        closesocket(s);
        return INVALID_SOCKET;
    }

    if (listen(s, 1) != 0)
    {
        printf("[TCP] listen failed, err=%d\n", WSAGetLastError());
        closesocket(s);
        return INVALID_SOCKET;
    }

    return s;
}

static void HandleStartCapture(SOCKET client, int slotIndex, const char* cmd)
{
    CaptureRequest req;
    DaqPacketHeader header;
    unsigned int seqNo;
    int payloadBytes;
    short* payload = NULL;
    float realAggHz = 0.0f;
    int rc;

    if (gAgentState == AGENT_STATE_BUSY)
    {
        SendText(client, "BUSY\n");
        return;
    }

    if (!ParseStartCaptureCommand(cmd, &req))
    {
        SendText(client, "ERROR BAD_COMMAND\n");
        return;
    }

    gAgentState = AGENT_STATE_BUSY;
    seqNo = ++gSeqNo;

    FillBasicHeader(&header, &req, seqNo);

    printf("[CMD] START_CAPTURE CH=%d RATE=%d SEC=%d RTU1=%u RTU2=%u\n",
           req.channelCount, req.requestedSampleRateHz, req.seconds,
           req.rtuAddr1, req.rtuAddr2);

    // Read RTU values once before DAQ capture.
    header.rtuStatus1 = ReadRtuValue(req.rtuAddr1, &header.rtuValue1);
    header.rtuStatus2 = ReadRtuValue(req.rtuAddr2, &header.rtuValue2);

    payloadBytes = req.channelCount * req.samplesPerChannel * sizeof(short);
    payload = (short*)malloc((size_t)payloadBytes);

    if (payload == NULL)
    {
        printf("[DAQ] malloc failed, bytes=%d\n", payloadBytes);
        header.status = HDR_STATUS_DAQ_ERROR;
        header.errorCode = 1001;
        header.payloadBytes = 0;
        SendAll(client, (const unsigned char*)&header, sizeof(header));
        gAgentState = AGENT_STATE_IDLE;
        return;
    }

    memset(payload, 0, (size_t)payloadBytes);

    rc = Capture8014WToMemory(
        slotIndex,
        payload,
        req.channelCount,
        req.requestedSampleRateHz,
        req.samplesPerChannel,
        &realAggHz
    );

    if (realAggHz > 0.0f)
    {
        header.actualSampleRateHz = realAggHz / (float)req.channelCount;
    }
    else
    {
        header.actualSampleRateHz = (float)req.requestedSampleRateHz;
    }

    if (rc == 0)
    {
        header.status = HDR_STATUS_OK;
        header.errorCode = 0;
        header.payloadBytes = (unsigned int)payloadBytes;

        if (!SendAll(client, (const unsigned char*)&header, sizeof(header)))
        {
            printf("[TCP] send header failed.\n");
        }
        else if (!SendAll(client, (const unsigned char*)payload, payloadBytes))
        {
            printf("[TCP] send payload failed.\n");
        }
        else
        {
            printf("[TCP] sent header=%u payload=%u bytes OK.\n",
                   (unsigned int)sizeof(header), header.payloadBytes);
        }
    }
    else
    {
        header.status = HDR_STATUS_DAQ_ERROR;
        header.errorCode = (unsigned int)(-rc);
        header.payloadBytes = 0;
        SendAll(client, (const unsigned char*)&header, sizeof(header));
        printf("[DAQ] capture failed rc=%d; sent error header.\n", rc);
    }

    free(payload);
    gAgentState = AGENT_STATE_IDLE;
}

static void TcpListenLoop(SOCKET listenSock, int slotIndex)
{
    while (1)
    {
        SOCKET client;
        char cmd[256];

        printf("[TCP] waiting for client...\n");
        client = accept(listenSock, NULL, NULL);

        if (client == INVALID_SOCKET)
        {
            printf("[TCP] accept failed, err=%d\n", WSAGetLastError());
            continue;
        }

        memset(cmd, 0, sizeof(cmd));
        if (!RecvCommandLine(client, cmd, sizeof(cmd)))
        {
            printf("[TCP] receive command failed.\n");
            closesocket(client);
            continue;
        }

        printf("[CMD] %s\n", cmd);

        if (strcmp(cmd, "PING") == 0)
        {
            SendText(client, "PONG\n");
        }
        else if (strcmp(cmd, "STATUS") == 0)
        {
            SendText(client, StateText());
        }
        else if (StartsWith(cmd, "START_CAPTURE"))
        {
            HandleStartCapture(client, slotIndex, cmd);
        }
        else
        {
            SendText(client, "ERROR BAD_COMMAND\n");
        }

        shutdown(client, SD_BOTH);
        closesocket(client);
    }
}

// =====================================================
// Entry point
// =====================================================
int _tmain(int argc, _TCHAR* argv[])
{
    WSADATA wsa;
    SOCKET listenSock;
    int slot;

    printf("DAQ Agent for WinCE / I-8014W / Modbus RTU\n");
    printf("Commands: PING, STATUS, START_CAPTURE CH=12 RATE=10000 SEC=10 RTU1=1 RTU2=2\n");
    printf("DaqPacketHeader size = %u bytes\n", (unsigned int)sizeof(DaqPacketHeader));

    if (sizeof(DaqPacketHeader) != 48)
    {
        printf("ERROR: DaqPacketHeader must be 48 bytes. Current=%u\n", (unsigned int)sizeof(DaqPacketHeader));
        return 10;
    }

    if (WSAStartup(MAKEWORD(2,2), &wsa) != 0)
    {
        printf("WSAStartup failed, err=%d\n", WSAGetLastError());
        return 1;
    }

    if (!InitModbus())
    {
        printf("[RTU] WARN: Modbus init failed. START_CAPTURE will report RTU errors.\n");
        // Continue, because DAQ may still be usable.
    }

    slot = FindFirstI8014W();
    if (slot < 0)
    {
        printf("ERROR: No I-8014W module found in slots 0..7\n");
        if (gModbusCom != INVALID_HANDLE_VALUE) CloseHandle(gModbusCom);
        WSACleanup();
        return 2;
    }

    printf("Found I-8014W at slot %d\n", slot);

    listenSock = StartTcpServer(kListenPort);
    if (listenSock == INVALID_SOCKET)
    {
        if (gModbusCom != INVALID_HANDLE_VALUE) CloseHandle(gModbusCom);
        WSACleanup();
        return 3;
    }

    printf("Listening on 0.0.0.0:%u\n", (unsigned)kListenPort);

    TcpListenLoop(listenSock, slot);

    closesocket(listenSock);
    if (gModbusCom != INVALID_HANDLE_VALUE) CloseHandle(gModbusCom);
    WSACleanup();
    return 0;
}
