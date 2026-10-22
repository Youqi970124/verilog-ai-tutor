module RefModule(input a, input b, input c, input d, output out1, output out2);
  assign out1 = a & ~b;
  assign out2 = c & ~d;
endmodule
