==========================================================================================
CSV SHA256 diff (sorted hash)
==========================================================================================
CSV                                                     Phase 1            Phase 4            status
------------------------------------------------------------------------------------------
strategy_1_1_1_3y_RR1.csv                               b1f5bae17298b1e3   b1f5bae17298b1e3   OK
strategy_1_1_1_3y_RR2.2.csv                             406435c8872e7f3a   406435c8872e7f3a   OK
strategy_1_1_1_sl_htf_3y_RR2.2.csv                      357762d721bc5970   357762d721bc5970   OK
strategy_1_1_2_3y_RR1.csv                               ec3c2b7ef3c06e97   ec3c2b7ef3c06e97   OK
strategy_1_1_2_3y_RR2.2.csv                             ed09abed30e1de9e   ed09abed30e1de9e   OK
strategy_1_1_3_3y_RR1.csv                               d346ad6a40fda046   d346ad6a40fda046   OK
strategy_1_1_3_3y_RR2.2.csv                             83921be4d248a95f   83921be4d248a95f   OK
strategy_1_1_4_3y_RR1.csv                               6d486b797904eed0   6d486b797904eed0   OK
strategy_1_1_4_3y_RR2.2.csv                             74a29a21374ea741   74a29a21374ea741   OK
strategy_1_2_0_full.csv                                 94a6f75f33291c20   94a6f75f33291c20   OK
strategy_1_2_0_no_top_ob.csv                            1215261316104b90   1215261316104b90   OK
strategy_rdrb_3y_RR1.csv                                f22ed3d1326a0eda   f22ed3d1326a0eda   OK
strategy_rdrb_3y_RR2.2.csv                              ca73a2e3d22d03af   ca73a2e3d22d03af   OK
strategy_rdrb_premium_3y_RR2.2.csv                      b9773638287642b7   b9773638287642b7   OK
vic_bos_3y_RR1.csv                                      228daa4343ad54ed   228daa4343ad54ed   OK
vic_bos_3y_RR2.2.csv                                    444fe7a8cbdfdb83   444fe7a8cbdfdb83   OK
vic_evot_backtest_3y_ob_RR1.csv                         12e8c51b161b1f02   12e8c51b161b1f02   OK
vic_evot_backtest_3y_ob_RR2.2.csv                       dba5487d0c6889bd   dba5487d0c6889bd   OK
optimize_1_1_1_swept_stage3.csv                         bd2068fc3152b668   bd2068fc3152b668   OK
analyze_1_1_1_swept_monthly.csv                         cd88d1e804196e5c   cd88d1e804196e5c   OK
optimize_1_1_2_stage3.csv                               b9ae2ddb40b3ad63   b9ae2ddb40b3ad63   OK
optimize_1_1_3_v1_stage3_compare_ep.csv                 577d272136d78014   577d272136d78014   OK

==========================================================================================
Metrics diff (РНа основных backtest-логах)
==========================================================================================

backtest_strategy_1_1_1.log
  RR= 1.0 ✓  P1: total= 144 WR= 61.7% PnL=  +33.0R   P4: total= 144 WR= 61.7% PnL=  +33.0R
  RR= 2.2 ✓  P1: total= 143 WR= 41.4% PnL=  +45.6R   P4: total= 143 WR= 41.4% PnL=  +45.6R

backtest_strategy_1_1_2.log
  RR= 1.0 ✓  P1: total= 449 WR= 53.8% PnL=  +34.0R   P4: total= 449 WR= 53.8% PnL=  +34.0R
  RR= 2.2 ✓  P1: total= 448 WR= 32.9% PnL=  +23.0R   P4: total= 448 WR= 32.9% PnL=  +23.0R

backtest_strategy_1_1_3.log
  RR= 1.0 ✓  P1: total= 125 WR= 52.5% PnL=   +6.0R   P4: total= 125 WR= 52.5% PnL=   +6.0R
  RR= 2.2 ✓  P1: total= 125 WR= 34.4% PnL=  +12.4R   P4: total= 125 WR= 34.4% PnL=  +12.4R

backtest_strategy_1_1_4.log
  RR= 1.0 ✓  P1: total=  53 WR= 52.8% PnL=   +3.0R   P4: total=  53 WR= 52.8% PnL=   +3.0R
  RR= 2.2 ✓  P1: total=  53 WR= 37.7% PnL=  +11.0R   P4: total=  53 WR= 37.7% PnL=  +11.0R

backtest_strategy_rdrb.log
  RR= 1.0 ✓  P1: total= 127 WR= 54.5% PnL=  +11.0R   P4: total= 127 WR= 54.5% PnL=  +11.0R
  RR= 2.2 ✓  P1: total= 127 WR= 35.0% PnL=  +14.6R   P4: total= 127 WR= 35.0% PnL=  +14.6R

backtest_vic_bos.log
  ⚠️ no metrics parsed: P1=0 P4=0

backtest_vic_evot.log
  ⚠️ no metrics parsed: P1=0 P4=0

==========================================================================================
SUMMARY: 0 CSV mismatches, 0 metric mismatches
==========================================================================================
✅ Refactor чистый. Все хеши и метрики совпадают.
