module mod_a(output out1, output out2, input in1, input in2, input in3, input in4);
  assign out1 = in1 & ~in2;
  assign out2 = in3 & ~in4;
endmodule
