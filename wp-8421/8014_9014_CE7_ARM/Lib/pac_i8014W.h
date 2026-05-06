// pac_i8014W_ReadFIFO_BlockMode add when Ver 1.0.0.9
// pac_i8014W_ReadFIFO_InISR add when Ver 1.0.0.9

#ifdef __cplusplus
extern "C" {
#endif

#ifdef _8014W_EXPORTS
	#define I8014WAPI __declspec(dllexport)
#else
	#define I8014WAPI __declspec(dllimport)
#endif

/*****[Error Code Definition]*****/
#define NoError				0
#define ID_ERROR			-1
#define SLOT_ERROR			-2
#define CHANNEL_ERROR		-3
#define GAIN_ERROR			-4
#define FIFO_EMPTY			-5
#define FIFO_LATCHED		-6
#define FIFO_OVERFLOW		-7
#define TX_NOTREADY			-8
#define FIFO_ISR_ERROR		-9
#define REG_SLOT_ISR_ERROR	-100
#define MAX_FIFO				4096

#define Average_Sample_Rate_DIFF_Error	-10
#define Average_Sample_Rate_SING_Error	-11
#define Average_Level_Error				-12


I8014WAPI short pac_i8014W_Init(int slot);
/*************************************
	[Basic Function]
	Used to initialize I-8014W / I-8014CW / I-9014 / I-9014C at specific slot.
		[input] slot: 0 ~ 7
		[output] return: Error Code.
*************************************/

I8014WAPI short pac_i8014W_GetLibVersion(void);
/*************************************
	[Basic Function]
	Used to get the library version.
		[output] return: version number.
				 For example: 0x106 = Rev:1.0.6
*************************************/

I8014WAPI void pac_i8014W_GetLibDate(char libDate[]);
/*************************************
	[Basic Function]
	Used to get the library built date.
		libDate: library built date
*************************************/

I8014WAPI short pac_i8014W_GetFirmwareVer_L1(int slot);
/*************************************
	[Basic Function]
	function to get the first FPGA firmware version.
		[input] slot: 0 ~ 7
		[output] return: firmware version
*************************************/

I8014WAPI short pac_i8014W_GetFirmwareVer_L2(int slot);
/*************************************
	[Basic Function]
	Used to get the second FPGA firmware version.
		[input] slot: 0 ~ 7
		[output] return: firmware version
*************************************/

I8014WAPI short pac_i8014W_GetSingleEndJumper(int slot);
/*************************************
	[Basic Function]
	Used to detection jumper status of I-8014W / I-9014.
	For I-8014CW and I-9014C always retuen 0.
		[input] slot: 0 ~ 7
		[output] return: 0 = differential mode, 1 = single-ended mode
*************************************/

I8014WAPI void pac_i8014W_ReadGainOffset(int slot,short gain,unsigned short* gainValue, short* offsetValue);
/*************************************
	[Basic Function]
	Used to read gain value and offset value of each range for I-8014 and I-9014.
	Every channel used the same gain value and offset value.
		[input] slot: 0 ~ 7
		[input] gain: 0 = +/- 10V,  1 = +/- 5V,  2 = +/- 2.5V  3 = +/- 1.25V  4 = +/- 20mA
		[output] *gainValue: gain value
		[output] *offsetValue: offset value
*************************************/

I8014WAPI void pac_i8014W_Read_mA_GainOffset(int slot,short ch ,unsigned short* GainValue, short* offsetValue);
/*************************************
	[Basic Function]
	Used to read gain value and offset value of each channel for I-8014CW and I-9014C
		[input] slot: 0 ~ 7
		[input] ch: 0 ~ 7
		[output] *GainValue: gain value
		[output] *offsetValue: offset value
*************************************/


I8014WAPI short pac_i8014W_ReadAIHex(int slot,short ch,short gain, short* hVal);
/*************************************
	[Basic Function]
	Used to read calibrated AI data
		[input] slot: 0 ~ 7
		[input] ch: 0 ~ 7(differential), 0 ~ 15(single-ended)
		[input] gain: 0 ~ 4
					  For I-8014W / I-9014, 0 = +/- 10V,  1=+/- 5V,  2=+/- 2.5V  3=+/- 1.25V  4=+/- 20mA
					  For I-8014CW / I-9014C, 4 = +/- 20mA
		[output] *hVal: calibrated hexadecimal format data
		[output] return: refer to error code
*************************************/

I8014WAPI short pac_i8014W_ReadAI(int slot,short ch,short gain, float* fVal);
/*************************************
	[Basic Function]
	Used to read calibrated AI data
		[input] slot: 0 ~ 7
		[output] ch: 0 ~ 7(differential), 0 ~ 15(single-ended)
		[input] gain: 0 ~ 4
					  For I-8014W / I-9014, 0 = +/- 10V,  1=+/- 5V,  2=+/- 2.5V  3=+/- 1.25V  4=+/- 20mA
					  For I-8014CW / I-9014C, 4 = +/- 20mA
		[output] fVal: calibrated float format data
		[output] return: refer to error code
*************************************/

I8014WAPI void pac_i8014W_ConfigMagicScan(int slot,short chArr[],short gainArr[],short scanChCount,float sampleRate,short scanMode,short triggerSource,short triggerState, float* realSampleRate);
/*************************************
	[Magic Scan Function]
	Used to configure Magic Scan, need to be called before "pac_i8014W_StartMagicScan"
		[input] slot: 0 ~ 7
		[input] chArr[]: {0,1,......6,7}(differential), {0,1,......14,15}(single-ended) array length depend on "scanChCount"
		[input] gainArr[]: {0,0,0,0,0,0,.....0,0,0,0} array length depend on "scanChCount"
						   For I-8014W / I-9014, 0 = +/- 10V,  1=+/- 5V,  2=+/- 2.5V  3=+/- 1.25V  4=+/- 20mA
						   For I-8014CW / I-9014C, 4 = +/- 20mA

		#1 chArr[] should match with gainArr[], for example,
		   chArr[0]=0 means channel 0 is been set in this array
		   gainArr[0]=0 means channel 0 is been set as +/- 10V

		[input] scanChCount: 0 ~ 8(differential), 0 ~ 16(single-ended)
		[input] sampleRate: 2~250Khz
		[input] scanMode: 1 ~ 2
						  1 : Standard mode
						  2 : Sample amd hole mode
		[input] triggerSource: 0 ~ 2
							   0 : Software trig
							   1 : Internal hardware trig
							   2 : External hardware trig
		[input] triggerState: 0~ 1, Only valid in "External hardware trig"
					  0 : Rising edge
					  1 : Falling edge
		[output] *realSampleRate: the real sample rate
*************************************/

I8014WAPI short pac_i8014W_StartMagicScan(int slot);
/*************************************
	[Magic Scan Function]
	Used to start Magic scan, after this function has been called, all the AI data will be save to FIFO
		[input] slot: 0 ~ 7
		[output] return: refer to error code
*************************************/

I8014WAPI short pac_i8014W_StopMagicScan(int slot);
/*************************************
	[Magic Scan Function]
	Used to stop Magic scan
		[input] slot: 0 ~ 7
		[output] return: refer to error code
*************************************/

I8014WAPI short pac_i8014W_ReadFIFO(int slot, short hexData[], short readCount,short* dataCountFromFIFO);
/*************************************
	[Magic Scan Function]
	Used to read data from FIFO in nonblock mode
		[input] slot: 0 ~ 7
		[output] hexData[]: raw data array
		[input] readCount: amount of data required
		[output] *dataCountFromFIFO: reading counts of data in this process
		[output] return: refer to error code
*************************************/

I8014WAPI short pac_i8014W_ReadFIFO_BlockMode(int slot, short hexData[], long readCount ,long* dataCountFromFIFO);
/*************************************
	[Magic Scan Function]
	Used to read data from FIFO in block mode
		[input] slot: 0 ~ 7
		[output] hexData[]: raw data array
		[input] readCount: amount of data required
		[output] *dataCountFromFIFO: reading counts of data in this process
		[output] return: refer to error code
*************************************/

// APIs for Magic Scan with ISR

#ifdef WIN32
	I8014WAPI short pac_i8014W_InstallMagicScanISR(int slot,void(__stdcall *isr)(int slot),short triggerLevel);
	/*************************************
		[Magic Scan Function]
		Used to install ISR function for XP-9000/XP-8000 based on WES platform
			[input] slot: 0 ~ 7
			[input] void(__stdcall *isr)(int slot): function pointer for ISR
			[input] triggerLevel: 0 ~ 7
								  0 : 8,   1 : 16
								  2 : 32,  3 : 64
								  4 : 128, 5 : 256
								  6 : 512, 7 : 2048
			[output] return: refer to error code
	*************************************/
#else
	I8014WAPI short pac_i8014W_InstallMagicScanISR(int slot,void(*isr)(int slot),short triggerLevel);
	/*************************************
		[Magic Scan Function]
		Used to install ISR function for XP-9000/XP-8000 based on CE platform
			[input] slot: 0 ~ 7
			[input] void(*isr)(int slot): function pointer for ISR
			[input] triggerLevel: 0 ~ 7
								  0 : 8,   1 : 16
								  2 : 32,  3 : 64
								  4 : 128, 5 : 256
								  6 : 512, 7 : 2048
			[output] return: refer to error code
	*************************************/
#endif

I8014WAPI short pac_i8014W_UnInstallMagicScanISR(int slot);
/*************************************
	[Magic Scan Function]
	Used to uninstall ISR function
		[input] slot: 0 ~ 7
		[output] return: refer to error code
*************************************/

I8014WAPI short pac_i8014W_ReadFIFO_InISR(int slot, short hexData[], short triggerLevel,short* dataCountFromFIFO);
/*************************************
	[Magic Scan Function]
	Used to read data from FIFO while using ISR function, should be called in ISR function
		[input] slot: 0 ~ 7
		[output] hexData[]: raw data array
		[input] triggerLevel: 0 ~ 7
							  0 : 8,   1 : 16
							  2 : 32,  3 : 64
							  4 : 128, 5 : 256
							  6 : 512, 7 : 2048
		[output] *dataCountFromFIFO: reading counts of data in this process
		[output] return: refer to error code
*************************************/

I8014WAPI void pac_i8014W_ClearInt(int slot);
/*************************************
	[Magic Scan Function]
	Used to clear the signal of interrupt, should be called in ISR function
		[input] slot: 0 ~ 7
*************************************/

I8014WAPI void  pac_i8014W_UnLockFIFO(int slot);
/*************************************
	[Magic Scan Function]
	Used to unlock FIFO when FIFO latched
		[input] slot: 0 ~ 7
*************************************/

I8014WAPI void pac_i8014W_ClearFIFO(int slot);
/*************************************
	[Magic Scan Function]
	Used to clear FIFO
		[input] slot: 0 ~ 7
*************************************/

I8014WAPI void pac_i8014W_CalibrateDataHex(int slot, short iGain,short dataFromFIFO, short* calibratedAI);
/*************************************
	[Magic Scan Function]
	Used to calibrate raw data which are read by magic scan (for I-8014W / I-9014)
		[input] slot: 0 ~ 7
		[input] iGain: 0 ~ 4
					   0 = +/- 10V  1 = +/- 5V  2 = +/- 2.5V  3 = +/- 1.25V  4 = +/- 20mA
		[input] dataFromFIFO: raw data
		[output] *calibratedAI: calibrated hexadecimal format data
*************************************/

I8014WAPI void pac_i8014W_CalibrateData(int slot, short iGain,short dataFromFIFO, float* calibratedAI);
/*************************************
	[Magic Scan Function]
	Used to calibrate the raw data read from magic scan (for I-8014W / I-9014)
		[input] slot: 0 ~ 7
		[input] iGain: 0 ~ 4
					   0 = +/- 10V  1 = +/- 5V  2 = +/- 2.5V  3 = +/- 1.25V  4 = +/- 20mA
		[input] dataFromFIFO: raw data
		[output] *calibratedAI: calibrated float format data
*************************************/

I8014WAPI void pac_i8014W_Calibrate_CH_mA_Hex(int slot, int ch ,short dataFromFIFO, short* calibratedAI);
/*************************************
	[Magic Scan Function]
	Used to calibrate the raw data read from magic scan (for I-8014CW / I-9014C)
		[input] slot: 0 ~ 7
		[input] ch: 0 ~ 7
		[input] dataFromFIFO: raw data
		[ourpur] *calibratedAI: calibrated hexadecimal format data
*************************************/

I8014WAPI void pac_i8014W_Calibrate_CH_mA(int slot, int ch ,short dataFromFIFO, float* calibratedAI);
/*************************************
	[Magic Scan Function]
	Used to calibrate the raw data read from magic scan (for I-8014CW / I-9014C)
		[input] slot: 0 ~ 7
		[input] ch: 0 ~ 7
		[input] dataFromFIFO: raw data
		[ourpur] *calibratedAI: calibrated float format data
*************************************/


/*=========The following 6 functions for only WinCE 6.0/7.0 platform=========*/
I8014WAPI short pac_i8014W_Start_Average_INT(int slot,short gain,float sample_rate,short average_level);
/*************************************
	[Average Function]
	Used to startup calculate data average with MagicScan function, the "pac_i8014W_Init" will also be called.
		[input] slot : 0 ~ 3(for four-slot host), 0 ~ 7(for eight-slot host)
		[input] gain : 0 ~ 4
						I-8014W  / I-9014  => range 0 : +/- 10V
											  range 1 : +/- 5V
											  range 2 : +/- 2.5V
											  range 3 : +/- 1.25V
											  range 4 : +/- 20mA
						I-8014CW / I-9014C => range 4 : +/- 20mA(Always)
		[input] sample_rate : 1 ~ 5000 Hz(differential), 1 ~ 2500 Hz(single-ended)
		[input] Average_Level : 0 ~ 7
						level 0 : Calculate average for every 1 data
						level 1 : Calculate average for every 2 data
						level 2 : Calculate average for every 4 data
						level 3 : Calculate average for every 8 data
						level 4 : Calculate average for every 16 data
						level 5 : Calculate average for every 32 data
						level 6 : Calculate average for every 64 data
						level 7 : Calculate average for every 256 data

		[output] return : Error code or Return code
						Error code :
							-100(DEC) : Install ISR Function Error.
							0x1000 : invalid module.
							0x1001 : slot is out of range.
							0x1002 : gain is out of range.
							0x1003 : sample_rate is out of range in differential mode.
							0x1004 : sample_rate is out of range in single-ended mode.
							0x1005 : average_level is out of range.
						Return code :
							0 : No error, find I-8014W / I-9014.
							1 : No error, find I-8014CW / I-9014C.

			#Data refresh frequency : 1/sample rate * average count
			for example, 1000 Hz, Average count 64 ==> 1ms * 64 = about 64ms
*************************************/

I8014WAPI short pac_i8014W_Stop_Average_INT(int slot);
/*************************************
	[Average Function]
	Used to stop the Average Function
		[input] slot : 0 ~ 3(for four-slot host), 0 ~ 7(for eight-slot host)
		[output] return : Error code or Return code
						Error code :
							0x1000 : invalid module.
							0x1001 : slot is out of range.
						Return code :
							0 : No error

*************************************/

I8014WAPI short pac_i8014W_ReadAIHex_Average_INT(int slot,short ch,short *hVal);
/*************************************
	[Average Function]
	Used to read one calibrated HEX format AI data
		[input] slot : 0 ~ 3(for four-slot host), 0 ~ 7(for eight-slot host)
		[input] ch : 0 ~ 7(differential), 0 ~ 15(single-ended)
		[output] *hVal : calibrated hexadecimal format data
		[output] return : Error code or Return code
						Error code :
							0x1000 : invalid module.
							0x1001 : slot is out of range.
							0x1002 : ch is out of range.
							0x2000 : FIFO Latch.
						Return code :
							0 : No error
*************************************/

I8014WAPI short pac_i8014W_ReadAI_Average_INT(int slot,short ch,float *fVal);
/*************************************
	[Average Function]
	Used to read one calibrated float format AI data
		[input] slot : 0 ~ 3(for four-slot host), 0 ~ 7(for eight-slot host)
		[input] ch : 0 ~ 7(differential), 0 ~ 15(single-ended)
		[output] *fVal : calibrated float format data
		[output] return : Error code or Return code
						Error code :
							0x1000 : invalid module.
							0x1001 : slot is out of range.
							0x1002 : ch is out of range.
							0x2000 : FIFO Latch.
						Return code :
							0 : No error
*************************************/

I8014WAPI short pac_i8014W_ReadAllAIHex_Average_INT(int slot,short hVal[]);
/*************************************
	[Average Function]
	Used to read multiple calibrated HEX format AI data
		[input] slot : 0 ~ 3(for four-slot host), 0 ~ 7(for eight-slot host)
		[output] hVal[] : calibrated hexadecimal format data,
						  length of hVal[] should be 8 in differential mode and should be 16 in single-ended mode.
		[output] return : Error code or Return code8
						  Error code :
								0x1000 : invalid module.
								0x1001 : slot is out of range.
								0x2000 : FIFO Latch.
						  Return code :
								0 : No error
*************************************/

I8014WAPI short pac_i8014W_ReadAllAI_Average_INT(int slot,float fVal[]);
/*************************************
	[Average Function]
	Used to read multiple calibrated float format AI data
		[input] slot : 0 ~ 3(for four-slot host), 0 ~ 7(for eight-slot host)
		[output] fVal[] : calibrated float format data,
						  length of fVal[] should be 8 in differential mode and should be 16 in single-ended mode.
		[output] return : Error code or Return code
						  Error code :
								0x1000 : invalid module.
								0x1001 : slot is out of range.
								0x2000 : FIFO Latch.
						  Return code :
								0 : No error
*************************************/


#ifdef __cplusplus
 }
#endif

